"""JSON 기반 기사 영속 저장소.

- 새로고침(크롤링)할 때마다 수집한 기사를 link 기준으로 누적 저장한다.
- 수집 시각(first_seen) 기준 RETENTION_DAYS 가 지난 기사는 자동 삭제한다.
  (작성일이 아니라 "처음 수집한 시각" 기준 — 한 번 본 기사는 작성일과 무관하게 5일간 유지된다.)
- 단, 북마크(bookmarked=True)한 기사는 기간과 무관하게 보존한다.
- GitHub 에 함께 커밋할 수 있도록 사람이 읽을 수 있는 JSON 으로 저장한다.
"""

import json
import os
import threading
from datetime import datetime, timedelta

DATA_PATH = os.path.join(os.path.dirname(__file__), "articles.json")
# 사용자별 북마크 저장 파일. 사용자가 입력한 "코드"별로 북마크한 link 목록을 담는다.
# 개인정보(누가 무엇을 북마크했는지)가 들어가므로 GitHub 에 올리지 않는다(.gitignore).
USER_BM_PATH = os.path.join(os.path.dirname(__file__), "user_bookmarks.json")
USER_WL_PATH = os.path.join(os.path.dirname(__file__), "user_watchlist.json")
RETENTION_DAYS = 5

_lock = threading.Lock()

# 크롤링이 매번 새로 채우는(=덮어써도 되는) 필드. date / first_seen / bookmarked 는 보존한다.
_MUTABLE_FIELDS = ("title", "summary", "image", "source", "category", "tier", "signals")


def _load() -> dict:
    if not os.path.exists(DATA_PATH):
        return {}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, DATA_PATH)


def _parse(iso: str) -> datetime:
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return datetime.now()


def _load_user_bm() -> dict:
    if not os.path.exists(USER_BM_PATH):
        return {}
    try:
        with open(USER_BM_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_user_bm(data: dict) -> None:
    tmp = USER_BM_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, USER_BM_PATH)


def get_user_bookmarks(user_code: str) -> list:
    """해당 코드(사용자)가 북마크한 link 목록을 반환한다."""
    if not user_code:
        return []
    with _lock:
        data = _load_user_bm()
    links = data.get(user_code)
    return list(links) if isinstance(links, list) else []


def set_user_bookmark(user_code: str, link: str, value: bool) -> bool:
    """코드(사용자)별 북마크 토글. 대상 기사가 저장소에 있으면 True, 없으면 False."""
    if not user_code or not link:
        return False
    with _lock:
        if link not in _load():  # 존재하는 기사만 북마크 가능
            return False
        data = _load_user_bm()
        links = data.get(user_code)
        if not isinstance(links, list):
            links = []
        if value:
            if link not in links:
                links.append(link)
        else:
            links = [l for l in links if l != link]
        if links:
            data[user_code] = links
        else:
            data.pop(user_code, None)  # 빈 사용자는 정리
        _save_user_bm(data)
    return True


def _all_bookmarked_links() -> set:
    """누구든 한 명이라도 북마크한 link 의 집합. (보존 판단용, _lock 보유 상태에서 호출)"""
    out: set = set()
    for links in _load_user_bm().values():
        if isinstance(links, list):
            out.update(links)
    return out


def _load_user_wl() -> dict:
    if not os.path.exists(USER_WL_PATH):
        return {}
    try:
        with open(USER_WL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_user_wl(data: dict) -> None:
    tmp = USER_WL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, USER_WL_PATH)


def get_user_watchlist(user_code: str) -> list:
    if not user_code:
        return []
    with _lock:
        data = _load_user_wl()
    companies = data.get(user_code)
    return list(companies) if isinstance(companies, list) else []


def set_user_watchlist(user_code: str, companies: list) -> None:
    if not user_code:
        return
    with _lock:
        data = _load_user_wl()
        cleaned = [c for c in companies if isinstance(c, str) and c.strip()]
        if cleaned:
            data[user_code] = cleaned
        else:
            data.pop(user_code, None)
        _save_user_wl(data)


def get_known_dates(links: list) -> dict:
    """이미 저장된 link 의 작성일을 반환한다 (HTML 매체 상세 재요청을 줄이기 위함)."""
    with _lock:
        data = _load()
    return {ln: data[ln]["date"] for ln in links if ln in data and data[ln].get("date")}


def upsert_many(items: list) -> None:
    """수집한 기사들을 누적 저장한다. 기존 기사는 작성일·북마크를 보존한 채 본문만 갱신."""
    now = datetime.now().isoformat()
    with _lock:
        data = _load()
        for it in items:
            link = it.get("link")
            if not link:
                continue
            existing = data.get(link)
            if existing:
                for fld in _MUTABLE_FIELDS:
                    if fld in it:
                        existing[fld] = it[fld]
            else:
                rec = {k: it.get(k) for k in _MUTABLE_FIELDS}
                rec["link"] = link
                rec["date"] = it.get("date") or now
                rec["first_seen"] = now
                data[link] = rec
        _save(data)


def prune(days: int = RETENTION_DAYS) -> int:
    """수집 시각(first_seen)이 days 일을 넘긴 기사를 삭제한다. 북마크는 보존. 삭제 건수 반환."""
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    with _lock:
        data = _load()
        bookmarked = _all_bookmarked_links()  # 누구든 북마크한 기사는 보존
        for link in list(data.keys()):
            rec = data[link]
            if link in bookmarked:
                continue
            # first_seen 이 없는 과거 데이터는 date 로 대체
            basis = rec.get("first_seen") or rec.get("date", "")
            if _parse(basis) < cutoff:
                del data[link]
                removed += 1
        if removed:
            _save(data)
    return removed


def all_items() -> list:
    """저장된 모든 기사를 작성일 내림차순으로 반환한다."""
    with _lock:
        data = _load()
    items = list(data.values())
    for item in items:
        if "signals" not in item:
            item["signals"] = []
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return items


# ════════════════════════════════════════════════════════════
#  채용(Jobs) 저장소 + 게임 관련 회사 리스트
#  - 공고엔 작성일이 없어 first_seen(수집 시각)을 날짜로 쓴다.
#  - 매 크롤마다 last_seen 을 갱신하고, 원티드에서 사라져(=last_seen 정체)
#    JOBS_STALE_DAYS 가 지나면 마감된 것으로 보고 정리한다.
# ════════════════════════════════════════════════════════════

JOBS_PATH = os.path.join(os.path.dirname(__file__), "jobs.json")
COMPANIES_PATH = os.path.join(os.path.dirname(__file__), "companies.json")
JOBS_STALE_DAYS = 2  # 이 기간 동안 다시 안 보이면 마감으로 간주

# 채용 공고에서 매 크롤마다 갱신해도 되는 필드 (first_seen/last_seen 은 보존)
_JOB_MUTABLE = ("title", "company_raw", "company_id", "skills",
                "address", "annual_from", "annual_to", "source")

# 시드: 게임 관련 회사 시작 목록. 자동 분류(원티드 게임 직군)에 안 잡히는
# 인접 기업 보강용. 사용자가 검색해서 추가/삭제한다. (마케팅사·아트 외주 등은
# 회사명을 확신하기 어려워 사용자가 직접 검색·추가하는 쪽이 정확)
SEED_COMPANIES = [
    {"name": "넥슨"}, {"name": "크래프톤"}, {"name": "넷마블"},
    {"name": "엔씨소프트"}, {"name": "카카오게임즈"}, {"name": "펄어비스"},
    {"name": "스마일게이트"}, {"name": "컴투스"}, {"name": "위메이드"},
    {"name": "시프트업"}, {"name": "넵튠"}, {"name": "그라비티"},
    {"name": "네오위즈"}, {"name": "웹젠"}, {"name": "데브시스터즈"},
    {"name": "뒤끝"},  # 게임 BaaS/인프라 예시
]


def _load_jobs() -> dict:
    if not os.path.exists(JOBS_PATH):
        return {}
    try:
        with open(JOBS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_jobs(data: dict) -> None:
    tmp = JOBS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, JOBS_PATH)


def upsert_jobs(jobs: list) -> None:
    """크롤한 공고를 link 기준 누적. 기존 공고는 last_seen 만 갱신."""
    now = datetime.now().isoformat()
    with _lock:
        data = _load_jobs()
        for j in jobs:
            link = j.get("link")
            if not link:
                continue
            existing = data.get(link)
            if existing:
                for fld in _JOB_MUTABLE:
                    if fld in j:
                        existing[fld] = j[fld]
                existing["last_seen"] = now
            else:
                rec = {fld: j.get(fld) for fld in _JOB_MUTABLE}
                rec["link"] = link
                rec["first_seen"] = now
                rec["last_seen"] = now
                data[link] = rec
        _save_jobs(data)


def prune_jobs(days: int = JOBS_STALE_DAYS) -> int:
    """last_seen 이 days 일을 넘긴(=원티드에서 사라진) 공고를 정리. 삭제 건수 반환."""
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    with _lock:
        data = _load_jobs()
        for link in list(data.keys()):
            basis = data[link].get("last_seen") or data[link].get("first_seen", "")
            if _parse(basis) < cutoff:
                del data[link]
                removed += 1
        if removed:
            _save_jobs(data)
    return removed


def all_jobs() -> list:
    """저장된 공고 전체를 수집 시각(first_seen) 내림차순으로 반환. date 필드 부여."""
    with _lock:
        data = _load_jobs()
    items = list(data.values())
    for it in items:
        it["date"] = it.get("first_seen")
    items.sort(key=lambda x: x.get("first_seen", ""), reverse=True)
    return items


def _load_companies():
    if not os.path.exists(COMPANIES_PATH):
        return None
    try:
        with open(COMPANIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_companies(data: list) -> None:
    tmp = COMPANIES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, COMPANIES_PATH)


def get_companies() -> list:
    """게임 관련 회사 리스트. 최초 호출 시 시드로 초기화한다."""
    with _lock:
        data = _load_companies()
        if data is None:
            data = [dict(c) for c in SEED_COMPANIES]
            _save_companies(data)
    return data


def add_company(name: str, company_id=None) -> bool:
    """회사를 크롤 리스트에 추가(이름 기준 중복 제거). 추가/이미존재 시 True."""
    name = (name or "").strip()
    if not name:
        return False
    with _lock:
        data = _load_companies()
        if data is None:
            data = [dict(c) for c in SEED_COMPANIES]
        if any((c.get("name", "").strip().casefold() == name.casefold()) for c in data):
            return True  # 이미 있음
        rec = {"name": name}
        if company_id:
            rec["company_id"] = company_id
        data.append(rec)
        _save_companies(data)
    return True


def remove_company(name: str) -> bool:
    """회사를 크롤 리스트에서 제거. 제거되면 True."""
    name = (name or "").strip()
    if not name:
        return False
    with _lock:
        data = _load_companies()
        if data is None:
            return False
        new = [c for c in data if c.get("name", "").strip().casefold() != name.casefold()]
        if len(new) == len(data):
            return False
        _save_companies(new)
    return True


# ── 국민연금 직원수 캐시 + 수동 등급(tier) override ──────────────
# 모두 "정규화된 회사명 키"(crawler._canonical_company 가 만든 키)를 키로 쓴다.
NPS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "nps_cache.json")
TIER_OVERRIDE_PATH = os.path.join(os.path.dirname(__file__), "tier_overrides.json")


def _load_json_map(path) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json_map(path, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def get_nps_cache() -> dict:
    with _lock:
        return _load_json_map(NPS_CACHE_PATH)


def nps_cache_set(key: str, employees, matched: str) -> None:
    """key(정규화 회사명) → 직원수/매칭된 사업장명 캐시. employees 는 int 또는 None."""
    if not key:
        return
    with _lock:
        data = _load_json_map(NPS_CACHE_PATH)
        data[key] = {"employees": employees, "matched": matched or ""}
        _save_json_map(NPS_CACHE_PATH, data)


def get_tier_overrides() -> dict:
    with _lock:
        return _load_json_map(TIER_OVERRIDE_PATH)


def set_tier_override(key: str, tier) -> bool:
    """key(정규화 회사명) → 등급(1/2/3) 수동 지정. tier 가 None/0 이면 해제."""
    if not key:
        return False
    with _lock:
        data = _load_json_map(TIER_OVERRIDE_PATH)
        if tier in (1, 2, 3):
            data[key] = tier
        else:
            data.pop(key, None)  # 해제
        _save_json_map(TIER_OVERRIDE_PATH, data)
    return True
