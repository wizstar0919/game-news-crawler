from flask import Flask, render_template, jsonify, request
from crawler import fetch_all, get_stats, sort_items
from translator import translate_to_korean
import crawler
import nps
import store
import time
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# 채용 데이터는 네트워크 부담이 커서 뉴스와 별도로 캐시(30분)하고,
# 화면에선 "채용" 탭을 누를 때 /api/jobs 로 지연 로드한다.
_jobs_cache = {"ts": 0}
JOBS_TTL = 1800


def _enrich_tiers(companies: list) -> list:
    """회사별 국민연금 직원수를 조회(캐시)하고 최종 등급을 적용한다.
    등급 우선순위: 수동 override > 큐레이트 키워드 목록 > 직원수 자동 > 소형."""
    cache = store.get_nps_cache()
    todo = [g for g in companies if g["key"] not in cache] if nps.has_key() else []
    if todo:
        def work(g):
            res = nps.lookup_employees(g["company"])
            return g["key"], (res[0] if res else None), (res[1] if res else "")
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(work, todo))
        for key, emp, matched in results:
            store.nps_cache_set(key, emp, matched)
        cache = store.get_nps_cache()
    for g in companies:
        g["employees"] = cache.get(g["key"], {}).get("employees")
        g["tier"] = crawler.resolve_tier(g["company"])
    companies.sort(key=lambda g: (g["tier"], -g["count"]))
    return companies


def get_jobs(force: bool = False) -> list:
    """등록 회사 기준으로 채용을 크롤·저장·정리한 뒤 회사 단위 집계를 반환."""
    now = time.time()
    if force or not _jobs_cache["ts"] or (now - _jobs_cache["ts"] >= JOBS_TTL):
        raw = crawler.crawl_jobs(store.get_companies())
        store.upsert_jobs(raw)
        store.prune_jobs()
        _jobs_cache["ts"] = now
    return _enrich_tiers(crawler.aggregate_jobs(store.all_jobs()))


@app.route("/")
def index():
    sort_by = request.args.get("sort", "date")
    items = sort_items(fetch_all(), sort_by)
    stats = get_stats(items)
    return render_template("index.html", items=items, stats=stats, sort_by=sort_by)


@app.route("/api/news")
def api_news():
    category = request.args.get("category")
    source = request.args.get("source")
    signal = request.args.get("signal")
    sort_by = request.args.get("sort", "date")
    items = fetch_all()
    if category and category != "all":
        items = [i for i in items if i["category"] == category]
    if source:
        items = [i for i in items if i["source"] == source]
    if signal and signal != "all":
        items = [i for i in items if signal in i.get("signals", [])]
    items = sort_items(items, sort_by)
    return jsonify({"count": len(items), "items": items})


@app.route("/api/refresh")
def api_refresh():
    items = fetch_all(force=True)
    return jsonify({"count": len(items), "stats": get_stats(items)})


@app.route("/api/bookmarks")
def api_bookmarks():
    """해당 코드(사용자)가 북마크한 link 목록을 반환한다."""
    code = (request.args.get("code") or "").strip()
    return jsonify({"links": store.get_user_bookmarks(code)})


@app.route("/api/bookmark", methods=["POST"])
def api_bookmark():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    link = data.get("link", "")
    bookmarked = bool(data.get("bookmarked", False))
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    if not link:
        return jsonify({"ok": False, "error": "link required"}), 400
    ok = store.set_user_bookmark(code, link, bookmarked)
    if not ok:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "link": link, "bookmarked": bookmarked})


@app.route("/api/watchlist", methods=["GET", "POST"])
def api_watchlist():
    if request.method == "GET":
        code = (request.args.get("code") or "").strip()
        return jsonify({"companies": store.get_user_watchlist(code)})
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    companies = data.get("companies", [])
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    store.set_user_watchlist(code, companies)
    return jsonify({"ok": True, "companies": companies})


@app.route("/api/jobs")
def api_jobs():
    """회사 단위로 집계된 채용 목록. '채용' 탭에서 지연 로드."""
    force = request.args.get("refresh") == "1"
    companies = get_jobs(force=force)
    return jsonify({"count": len(companies), "companies": companies})


@app.route("/api/company-search")
def api_company_search():
    """원티드 회사 검색 (검색해서 바로 추가하기 용)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    try:
        results = crawler.search_companies(q, limit=10)
    except Exception as e:
        return jsonify({"results": [], "error": str(e)}), 502
    # 정규화 키로 비교해 변형명(넥슨코리아(NEXON) 등)도 같은 회사로 인식
    reg_keys = {crawler._canonical_company(c.get("name", ""))[1] for c in store.get_companies()}
    for r in results:
        r["registered"] = crawler._canonical_company(r.get("name", ""))[1] in reg_keys
    return jsonify({"results": results})


@app.route("/api/companies", methods=["GET", "POST"])
def api_companies():
    """게임 관련 회사 크롤 리스트 조회(GET) / 추가(POST)."""
    if request.method == "GET":
        return jsonify({"companies": store.get_companies()})
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    store.add_company(name, data.get("company_id"))
    _jobs_cache["ts"] = 0  # 다음 조회 때 새 회사 반영되도록 캐시 무효화
    return jsonify({"ok": True, "companies": store.get_companies()})


@app.route("/api/companies/remove", methods=["POST"])
def api_companies_remove():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    ok = store.remove_company(name)
    _jobs_cache["ts"] = 0
    return jsonify({"ok": ok, "companies": store.get_companies()})


@app.route("/api/company-tier", methods=["POST"])
def api_company_tier():
    """회사 등급 수동 지정/해제. tier 1/2/3, 또는 0/null 이면 해제(자동값으로 복귀)."""
    data = request.get_json(silent=True) or {}
    company = (data.get("company") or "").strip()
    tier = data.get("tier")
    if not company:
        return jsonify({"ok": False, "error": "company required"}), 400
    _, key = crawler._canonical_company(company)
    store.set_tier_override(key, tier if tier in (1, 2, 3) else None)
    return jsonify({"ok": True, "company": company, "tier": crawler.resolve_tier(company)})


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    summary = data.get("summary", "")
    return jsonify({
        "title": translate_to_korean(title),
        "summary": translate_to_korean(summary),
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
