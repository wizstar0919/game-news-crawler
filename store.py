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
RETENTION_DAYS = 5

_lock = threading.Lock()

# 크롤링이 매번 새로 채우는(=덮어써도 되는) 필드. date / first_seen / bookmarked 는 보존한다.
_MUTABLE_FIELDS = ("title", "summary", "image", "source", "category", "tier")


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
                rec["bookmarked"] = False
                data[link] = rec
        _save(data)


def prune(days: int = RETENTION_DAYS) -> int:
    """수집 시각(first_seen)이 days 일을 넘긴 기사를 삭제한다. 북마크는 보존. 삭제 건수 반환."""
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    with _lock:
        data = _load()
        for link in list(data.keys()):
            rec = data[link]
            if rec.get("bookmarked"):
                continue
            # first_seen 이 없는 과거 데이터는 date 로 대체
            basis = rec.get("first_seen") or rec.get("date", "")
            if _parse(basis) < cutoff:
                del data[link]
                removed += 1
        if removed:
            _save(data)
    return removed


def set_bookmark(link: str, value: bool) -> bool:
    """북마크 토글. 대상이 있으면 True, 없으면 False."""
    with _lock:
        data = _load()
        if link not in data:
            return False
        data[link]["bookmarked"] = bool(value)
        _save(data)
    return True


def all_items() -> list:
    """저장된 모든 기사를 작성일 내림차순으로 반환한다."""
    with _lock:
        data = _load()
    items = list(data.values())
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return items
