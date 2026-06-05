from flask import Flask, render_template, jsonify, request
from crawler import fetch_all, get_stats, sort_items
from translator import translate_to_korean
import crawler
import nps
import dart
import score
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


# ── 게임사 디렉토리 (타겟 발굴) ────────────────────────────────
# 큐레이트 메이저: 게임 업종코드 크롤에 안 잡히는 대형사(응용SW 코드로 등록 등).
# 국민연금 직원수 + DART 매출로 보강해 디렉토리에 합친다.
_MAJOR_NAMES = [
    "넥슨", "넷마블", "엔씨소프트", "크래프톤", "카카오게임즈", "펄어비스",
    "스마일게이트", "컴투스", "위메이드", "웹젠", "네오위즈", "그라비티",
    "시프트업", "데브시스터즈", "넵튠", "조이시티", "넥슨게임즈", "넥써쓰",
    "라인게임즈", "액토즈소프트", "엠게임", "한빛소프트", "미투온",
]

# 하이브리드 규모 기준 — 직원수·매출 중 "더 큰 쪽"으로 등급을 준다.
#   대형(1): 직원 300명+ 또는 매출 300억+
#   중형(2): 직원 100명+ 또는 매출 100억+
#   소형(3): 그 미만
EMP_LARGE, EMP_MID = 300, 100
REV_LARGE, REV_MID = 300e8, 100e8  # 원 단위


def _hybrid_tier(company: dict, override) -> int:
    """수동 override > (큐레이트 명단·직원수·매출 중 가장 큰 등급)."""
    if override in (1, 2, 3):
        return override
    tiers = []
    kw = crawler._company_tier(company["company"])  # 큐레이트 대형/중형 명단
    if kw in (1, 2):
        tiers.append(kw)
    emp = company.get("employees") or 0
    if emp:
        tiers.append(1 if emp >= EMP_LARGE else 2 if emp >= EMP_MID else 3)
    rev = company.get("revenue")
    if rev:
        tiers.append(1 if rev >= REV_LARGE else 2 if rev >= REV_MID else 3)
    return min(tiers) if tiers else 3  # min = 가장 큰 등급(1=대형)

_dir_build_lock = __import__("threading").Lock()


def _server_job_counts() -> dict:
    """저장된 채용 공고를 회사(정규화 키)별 공고 수로 집계. 서버·인프라 직군 신호."""
    counts = {}
    for g in crawler.aggregate_jobs(store.all_jobs()):
        counts[g["key"]] = g.get("count", 0)
    return counts


def build_directory() -> list:
    """게임사 디렉토리를 새로 구성한다(무거움 → 하루 1회).
    게임 업종코드 크롤 + 큐레이트 메이저 병합 → 매출·서버채용·타겟점수 결합."""
    companies = crawler.crawl_game_companies()
    seen = {c["key"] for c in companies}

    # 큐레이트 메이저 중 크롤에 안 잡힌 회사를 국민연금 직원수로 보강해 추가
    for name in _MAJOR_NAMES:
        disp, key = crawler._canonical_company(name)
        if key in seen:
            continue
        stats = nps.lookup_stats(name) if nps.has_key() else None
        companies.append({
            "company": name, "key": key,
            "employees": (stats or {}).get("employees", 0),
            "net_hire": (stats or {}).get("net_hire", 0),
            "payroll": (stats or {}).get("payroll", 0),
            "region": "", "industry": "게임", "biz_no": None,
        })
        seen.add(key)

    job_counts = _server_job_counts()

    # 전수 매출 조회 — 직원 적어도 매출 큰 회사(자산 경량 히트작 스튜디오)를 놓치지 않도록
    # 모든 회사를 DART 로 조회한다. 비상장(미공시)은 즉시 None 이라 부담이 적다.
    revenues = {}
    if dart.has_key():
        def work(c):
            r = dart.lookup_revenue(c["company"])
            return c["key"], (r[0] if r else None)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for key, rev in ex.map(work, companies):
                revenues[key] = rev

    # 하이브리드 등급(대/중/소): 직원수·매출·명단 중 가장 큰 신호로.
    overrides = store.get_tier_overrides()
    for c in companies:
        c["revenue"] = revenues.get(c["key"])
        c["tier"] = _hybrid_tier(c, overrides.get(c["key"]))
        c["server_jobs"] = job_counts.get(c["key"], 0)
        score.compute(c)

    companies.sort(key=lambda c: -c["score"])
    return companies


def get_directory(force: bool = False) -> dict:
    """디렉토리를 캐시에서 읽거나(신선하면) 새로 빌드해 반환한다."""
    if not force and store.directory_is_fresh():
        return store.get_directory()
    with _dir_build_lock:
        if not force and store.directory_is_fresh():
            return store.get_directory()
        companies = build_directory()
        store.save_directory(companies)
    return store.get_directory()


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


@app.route("/api/directory")
def api_directory():
    """게임사 디렉토리. 타겟점수·직원수·매출·서버채용·지역. '디렉토리' 탭에서 지연 로드."""
    force = request.args.get("refresh") == "1"
    data = get_directory(force=force) or {"updated": None, "companies": []}
    return jsonify({
        "updated": data.get("updated"),
        "count": len(data.get("companies", [])),
        "companies": data.get("companies", []),
    })


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
