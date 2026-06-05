import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re
import unicodedata

import store
import nps

SOURCES = {
    "global": [
        {"name": "GameSpot", "url": "https://www.gamespot.com/feeds/mashup/", "category": "global"},
        {"name": "IGN", "url": "https://feeds.feedburner.com/ign/all", "category": "global"},
        {"name": "Polygon", "url": "https://www.polygon.com/rss/index.xml", "category": "global"},
        {"name": "Kotaku", "url": "https://kotaku.com/rss", "category": "global"},
        {"name": "Eurogamer", "url": "https://www.eurogamer.net/feed", "category": "global"},
    ],
    "korea": [
        {"name": "GameMeca", "url": "https://www.gamemeca.com/rss.php", "category": "korea"},
    ],
    "media": [
        {"name": "PNN", "url": "https://www.ipnn.co.kr/rss/allArticle.xml", "category": "media"},
        {"name": "게임어바웃", "url": "https://www.gameabout.com/rss/allArticle.xml", "category": "media"},
        {"name": "게임톡", "url": "https://www.gametoc.co.kr/rss/allArticle.xml", "category": "media"},
        {"name": "게임뷰", "url": "https://www.gamevu.co.kr/rss/allArticle.xml", "category": "media"},
        {"name": "게임인사이트", "url": "https://www.gameinsight.co.kr/rss/allArticle.xml", "category": "media"},
        {"name": "게임플", "url": "https://www.gameple.co.kr/rss/allArticle.xml", "category": "media"},
        {"name": "경향게임스", "url": "https://www.khgames.co.kr/rss/allArticle.xml", "category": "media"},
        {"name": "뉴스앤게임(ZDNet)", "url": "https://zdnet.co.kr/feed", "category": "media"},
    ],
    "aws": [
        {"name": "AWS Game Tech Blog", "url": "https://aws.amazon.com/blogs/gametech/feed/", "category": "aws"},
        {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/", "category": "aws"},
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

ESPORTS_KEYWORDS = [
    "e스포츠", "이스포츠", "esports", "e-sports", "esport",
    " LCK", " LPL", " LEC", " LCS", " LJL", " LLA", " VCT",
    " ASL", " PMPS", " MSI", "EWC", "월드 챔피언십", "월즈",
    "프로게이머", "프로 게이머", "프로팀",
    "[포토]", "[ASL]", "[LCK]", "[LCS]",
    "젠지", "Gen.G", "한화생명e", "농심 레드포스", "kt 롤스터", "디플러스",
    "페이커", "구마유시", "데프트", "쇼메이커", "쵸비", "캐니언",
    "발로란트", "Valorant", "오버워치 리그", "Dota 2", "도타 2",
]

# 게임사 규모 분류 — "회사 규모(매출·상장)" 기준.
#   대형(1): 주요/상장 퍼블리셔(국내 상장 중견사 포함) + 글로벌 메이저
#   중형(2): 검증된 중소 상장사·스튜디오
#   소형(3): 위 목록에 없는 나머지(인디·신생·비상장 소규모)
# 회사를 올리거나 내리려면 이 딕셔너리에서 이름만 옮기면 된다.
COMPANY_TIERS = {
    1: [
        # 국내 주요/상장 퍼블리셔 (중견 상장사 포함해 상향)
        "넥슨", "Nexon", "엔씨소프트", "엔씨", "NCSOFT", "NCSoft", "NC ",
        "크래프톤", "Krafton", "넷마블", "Netmarble",
        "카카오게임즈", "Kakao Games", "카카오", "Kakao",
        "펄어비스", "Pearl Abyss", "스마일게이트", "Smilegate",
        "컴투스", "Com2uS", "위메이드", "Wemade",
        "웹젠", "Webzen", "네오위즈", "Neowiz", "NHN",
        "그라비티", "Gravity", "시프트업", "Shift Up",
        "데브시스터즈", "Devsisters", "라인게임즈", "조이시티",
        "넥써쓰", "액션스퀘어",  # 코스닥 205500, 구 액션스퀘어(2025.2 사명변경)
        # 글로벌 메이저 퍼블리셔
        "Nintendo", "닌텐도", "Sony", "소니", "Microsoft", "마이크로소프트",
        "Activision", "Blizzard", "블리자드", "EA", "Electronic Arts",
        "Ubisoft", "유비소프트", "Take-Two", "Rockstar",
        "Tencent", "텐센트", "Epic Games", "에픽게임즈",
        "Valve", "밸브", "Steam", "스팀", "Riot", "라이엇",
        "miHoYo", "미호요", "HoYoverse", "호요버스",
        "Capcom", "캡콤", "Square Enix", "스퀘어에닉스",
        "Bandai Namco", "반다이남코", "Konami", "코나미",
        "CD Projekt", "Bethesda", "베데스다", "2K",
    ],
    2: [
        # 검증된 중소 상장사·스튜디오 (필요 시 자유롭게 조정)
        "액토즈소프트", "엠게임", "한빛소프트", "넵튠", "Neptune",
        "베이글코드", "Bagelcode", "슈퍼진",
    ],
}


SIGNAL_KEYWORDS = {
    "투자유치": [
        "투자유치", "투자 유치", "펀딩", "시리즈 A", "시리즈A",
        "시리즈 B", "시리즈B", "시리즈 C", "시리즈C",
        "Series A", "Series B", "funding", "raised $", "investment round",
    ],
    "신작출시": [
        "신작 출시", "신작출시", "정식 출시", "정식출시", "게임 출시",
        "사전 예약", "사전예약", "얼리 액세스", "신규 게임",
        "game launch", "game release", "now available", "early access",
        "officially launches", "new game",
    ],
    "글로벌출시": [
        "글로벌 출시", "글로벌출시", "글로벌 런칭", "글로벌 서비스",
        "해외 출시", "해외출시", "글로벌 진출", "해외 진출",
        "global launch", "worldwide launch", "global release", "launches globally",
    ],
    "서버장애": [
        "서버 장애", "서버장애", "접속 장애", "서버 오류",
        "긴급 점검", "긴급점검", "서버 다운",
        "server outage", "downtime", "server down",
    ],
    "채용": [
        "개발자 채용", "엔지니어 채용", "백엔드 채용", "서버 채용",
        "백엔드 개발자", "채용 공고",
        "is hiring", "we're hiring", "job opening", "backend engineer",
        "server engineer",
    ],
}


def _signal_tags(text: str) -> list:
    if not text:
        return []
    tags = []
    low = text.lower()
    for tag, keywords in SIGNAL_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in low:
                tags.append(tag)
                break
    return tags


def _company_tier(text: str) -> int:
    if not text:
        return 3
    for tier in (1, 2):
        for kw in COMPANY_TIERS[tier]:
            if kw in text:
                return tier
    return 3


def _is_esports(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    for kw in ESPORTS_KEYWORDS:
        if kw.startswith(" "):
            if kw.lower() in (" " + low):
                return True
        elif kw.lower() in low:
            return True
    return False

# ts: 마지막으로 외부 사이트를 크롤한 시각. 화면 데이터는 항상 store 에서 읽으므로
# 캐시는 "재크롤 여부"만 판단한다(북마크 등 저장소 변경이 즉시 반영되도록).
_cache = {"ts": 0}
CACHE_TTL = 600

HTML_OUTLETS = [
    {
        "name": "게임동아",
        "list_url": "https://game.donga.com/",
        "article_re": r"^(?://|https?://)game\.donga\.com/(\d+)/?$",
        "link_base": "https://",
    },
    {
        "name": "매경게임진",
        "list_url": "https://game.mk.co.kr/",
        "article_re": r"^(?:https?://game\.mk\.co\.kr)?/news/it/(\d+)$",
        "link_base": "https://game.mk.co.kr",
    },
    {
        "name": "데일리게임",
        "list_url": "https://www.dailygame.co.kr/",
        "article_re": r"view\.php\?ud=([^&\"'\s]+)",
        "link_base": "https://www.dailygame.co.kr",
    },
    {
        "name": "게임포커스",
        "list_url": "http://www.gamefocus.co.kr/",
        "article_re": r"detail\.php\?number=(\d+)$",
        "link_base": "http://www.gamefocus.co.kr",
    },
]


def _clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:280] + ("…" if len(text) > 280 else "")


def _extract_image(entry) -> str | None:
    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")
    if "links" in entry:
        for link in entry.links:
            if link.get("type", "").startswith("image"):
                return link.get("href")
    summary = entry.get("summary", "") or entry.get("description", "")
    if summary:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
        if m:
            return m.group(1)
    return None


def _parse_date(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                continue
    return datetime.now()


# 상세 페이지에서 작성일로 인정할 meta 키 (소문자 비교)
_DATE_META_KEYS = {
    "article:published_time", "article:modified_time", "og:updated_time",
    "datepublished", "date", "pubdate", "publishdate", "sailthru.date",
}

# "2026-05-31", "2026.05.31 15:04", "2026년 5월 31일 15:04" 등
_DATE_RE = re.compile(
    r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})(?:\D{1,3}?(\d{1,2}):(\d{2}))?"
)


def _to_naive_iso(dt: datetime) -> str:
    """tz 가 있으면 로컬 시간으로 변환 후 tz 를 떼고 ISO 문자열로 통일한다."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()


def _parse_date_str(s: str):
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d",
        "%Y/%m/%d %H:%M", "%Y/%m/%d",
        "%Y년 %m월 %d일 %H:%M", "%Y년 %m월 %d일",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = _DATE_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mm = int(m.group(5)) if m.group(5) else 0
        try:
            return datetime(y, mo, d, hh, mm)
        except ValueError:
            return None
    return None


def _extract_article_date(html: str):
    """기사 상세 HTML 에서 작성일을 추출한다. (JSON-LD → meta → <time> → 본문 정규식)"""
    if not html:
        return None
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if m:
        d = _parse_date_str(m.group(1))
        if d:
            return d
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower()
        if key in _DATE_META_KEYS and meta.get("content"):
            d = _parse_date_str(meta["content"])
            if d:
                return d
    t = soup.find("time")
    if t:
        d = _parse_date_str(t.get("datetime") or t.get_text(" ", strip=True))
        if d:
            return d
    return None


# HTML 스크래핑 작성일은 신뢰도가 낮다(템플릿/저작권 고정 날짜를 긁는 경우가 있음).
# 미래이거나 너무 오래된(아래 일수 초과) 값은 버리고 수집 시각으로 대체한다.
_HTML_DATE_MAX_AGE_DAYS = 30


def _sane_html_date(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return None
    now = datetime.now()
    if dt > now + timedelta(days=1):
        return None  # 미래 날짜 → 오파싱
    if dt < now - timedelta(days=_HTML_DATE_MAX_AGE_DAYS):
        return None  # 지나치게 오래됨 → 고정 날짜로 의심
    return iso_str


def _fetch_article_date(url: str):
    """기사 상세 페이지를 받아 신뢰 가능한 작성일(naive ISO)을 반환한다. 실패/비정상 시 None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.raise_for_status()
        html = r.content.decode(r.encoding or "utf-8", errors="replace")
        d = _extract_article_date(html)
        return _sane_html_date(_to_naive_iso(d)) if d else None
    except Exception:
        return None


def _is_game_related(text: str) -> bool:
    keywords = [
        "game", "gaming", "games", "gamer", "esport", "unity", "unreal",
        "playstation", "xbox", "nintendo", "steam", "studio", "developer",
        "lumberyard", "open 3d", "o3de", "graviton",
    ]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


def fetch_one(source: dict) -> list:
    items = []
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:20]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            if not title or not link:
                continue

            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = _clean_html(summary_raw)

            blob = f"{title} {summary}"

            if source["name"] == "AWS News Blog":
                if not _is_game_related(blob):
                    continue

            if _is_esports(blob):
                continue

            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "image": _extract_image(entry),
                "date": _parse_date(entry).isoformat(),
                "source": source["name"],
                "category": source["category"],
                "tier": _company_tier(blob),
                "signals": _signal_tags(blob),
            })
    except Exception as e:
        print(f"[crawler] {source['name']} failed: {e}")
    return items


def _resolve_link(href: str, link_base: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return link_base + href
    if not href.startswith("http"):
        return link_base.rstrip("/") + "/" + href
    return href


def fetch_html_outlet(outlet: dict) -> list:
    items: list = []
    try:
        r = requests.get(outlet["list_url"], headers=HEADERS, timeout=10)
        r.raise_for_status()
        text = r.content.decode(r.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        article_re = re.compile(outlet["article_re"])

        url_to_anchors: dict = {}
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = article_re.search(href)
            if not m:
                continue
            txt = a.get_text(strip=True)
            if not txt or len(txt) < 8:
                continue
            key = m.group(0)
            if key not in url_to_anchors:
                url_to_anchors[key] = {"href": href, "texts": []}
            if txt not in url_to_anchors[key]["texts"]:
                url_to_anchors[key]["texts"].append(txt)

        for key, data in url_to_anchors.items():
            texts = data["texts"]
            title_candidates = [t for t in texts if len(t) <= 120]
            if title_candidates:
                title = min(title_candidates, key=len)
            else:
                shortest = min(texts, key=len)
                title = shortest[:80].rstrip() + "…"

            longer = [t for t in texts if len(t) > len(title) + 10]
            summary = max(longer, key=len)[:220] if longer else ""

            blob = f"{title} {summary}"
            if _is_esports(blob):
                continue

            items.append({
                "title": title,
                "link": _resolve_link(data["href"], outlet["link_base"]),
                "summary": summary,
                "image": None,
                "date": None,  # 실제 작성일은 fetch_all 에서 상세 페이지로 보강
                "source": outlet["name"],
                "category": "media",
                "tier": _company_tier(blob),
                "signals": _signal_tags(blob),
            })
            if len(items) >= 20:
                break
    except Exception as e:
        print(f"[html outlet] {outlet['name']} failed: {e}")
    return items


def _parse_kgma_listing(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    items: list = []
    seen = set()
    for a in soup.find_all("a", href=re.compile(r"cd=g0201.*cm=v.*ud=(\d+)")):
        m = re.search(r"ud=(\d+)", a["href"])
        if not m:
            continue
        ud = m.group(1)
        if ud in seen:
            continue
        seen.add(ud)
        # walk up to find a container with enough text
        container = a
        for _ in range(6):
            if container is None:
                break
            txts = [t.strip() for t in container.stripped_strings if t.strip()]
            if len(txts) >= 2 and any(len(t) > 15 for t in txts):
                break
            container = container.parent
        if container is None:
            continue
        # Extract this single item's data — find the closest text block
        # The pattern is: name (short), description (long), "자세히보기"
        all_texts = [t.strip() for t in container.stripped_strings if t.strip()]
        # find this item's segment by clipping around it
        # de-dupe by taking each unique text block
        name, desc = None, None
        for i, t in enumerate(all_texts):
            if t == "자세히보기" and i >= 2:
                desc = all_texts[i - 1]
                name = all_texts[i - 2]
                break
        if not name:
            continue
        img = a.find("img") or container.find("img")
        img_src = img.get("src") if img else None
        items.append({
            "ud": ud,
            "name": name,
            "desc": desc or "",
            "image": img_src,
            "detail_url": KGMA_BASE + "/" + a["href"].lstrip("/"),
        })
    return items


def _fetch_kgma_homepage(detail_url: str) -> str | None:
    try:
        r = requests.get(detail_url, headers=HEADERS, timeout=8)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("http") and "k-gma.com" not in href:
                return href
    except Exception as e:
        print(f"[kgma detail] {detail_url} failed: {e}")
    return None


def fetch_kgma(force: bool = False) -> list:
    now = time.time()
    if not force and _kgma_cache["data"] and (now - _kgma_cache["ts"] < KGMA_CACHE_TTL):
        return _kgma_cache["data"]

    raw_items: list = []
    for pg in range(1, 6):
        url = f"{KGMA_BASE}/subsection.php?cd=g0201&sn=&pg={pg}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            page_items = _parse_kgma_listing(r.text)
            if not page_items:
                break
            existing = {i["ud"] for i in raw_items}
            new_items = [i for i in page_items if i["ud"] not in existing]
            if not new_items:
                break
            raw_items.extend(new_items)
        except Exception as e:
            print(f"[kgma list pg={pg}] failed: {e}")
            break

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch_kgma_homepage, it["detail_url"]): it for it in raw_items}
        for f in as_completed(futures):
            it = futures[f]
            it["homepage"] = f.result()

    items = []
    today = datetime.now().isoformat()
    for it in raw_items:
        items.append({
            "title": it["name"],
            "link": it.get("homepage") or it["detail_url"],
            "summary": it["desc"],
            "image": it["image"],
            "date": today,
            "source": "K-GMA 매체",
            "category": "media",
        })
    _kgma_cache["data"] = items
    _kgma_cache["ts"] = now
    return items


def _enrich_html_dates(html_items: list) -> None:
    """HTML 매체 기사의 실제 작성일을 채운다.
    이미 저장소에 있는 link 는 저장된 날짜를 재사용하고, 새 기사만 상세 페이지를 요청한다."""
    known = store.get_known_dates([i["link"] for i in html_items])
    to_fetch = [i for i in html_items if i["link"] not in known]

    fetched: dict = {}
    if to_fetch:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_fetch_article_date, i["link"]): i["link"] for i in to_fetch}
            for f in as_completed(futures):
                fetched[futures[f]] = f.result()

    for i in html_items:
        link = i["link"]
        if link in known:
            i["date"] = known[link]
        else:
            i["date"] = fetched.get(link) or datetime.now().isoformat()


def fetch_all(force: bool = False) -> list:
    """저장소(store)에 누적된 기사 전체를 반환한다.
    마지막 크롤 후 CACHE_TTL 이 지났거나 force 면 외부 사이트를 다시 크롤해 누적·정리한다.
    화면 데이터는 항상 store 에서 읽으므로 북마크 변경이 즉시 반영된다."""
    now = time.time()
    stale = force or not _cache["ts"] or (now - _cache["ts"] >= CACHE_TTL)

    if stale:
        all_sources = [s for group in SOURCES.values() for s in group]
        rss_items: list = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(fetch_one, s): s for s in all_sources}
            for f in as_completed(futures):
                rss_items.extend(f.result())

        html_items: list = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(fetch_html_outlet, o): o for o in HTML_OUTLETS}
            for f in as_completed(futures):
                html_items.extend(f.result())

        _enrich_html_dates(html_items)

        # 누적 저장 → 5일(first_seen) 지난 기사 정리(북마크 제외)
        store.upsert_many(rss_items + html_items)
        store.prune()
        _cache["ts"] = now

    return store.all_items()


def get_stats(items: list) -> dict:
    by_source: dict = {}
    by_category = {"global": 0, "korea": 0, "aws": 0, "media": 0}
    by_tier = {1: 0, 2: 0, 3: 0}
    bookmarks = 0
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1
        by_category[it["category"]] = by_category.get(it["category"], 0) + 1
        by_tier[it.get("tier", 3)] = by_tier.get(it.get("tier", 3), 0) + 1
        if it.get("bookmarked"):
            bookmarks += 1
    return {
        "total": len(items),
        "by_source": by_source,
        "by_category": by_category,
        "by_tier": by_tier,
        "bookmarks": bookmarks,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def sort_items(items: list, sort_by: str = "date") -> list:
    if sort_by == "tier":
        return sorted(items, key=lambda x: (x.get("tier", 3), -_iso_to_ts(x["date"])))
    return sorted(items, key=lambda x: x["date"], reverse=True)


def _iso_to_ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return 0.0


# ════════════════════════════════════════════════════════════
#  채용(Jobs) 크롤링
#  "어느 게임(관련) 회사가 지금 서버/인프라 사람을 뽑는가" = AWS 영업 신호.
#  뉴스와 데이터 성격이 달라(회사 단위 집계) 별도 파이프라인으로 둔다.
#
#  소스 전략:
#   - 원티드 게임 직군 카테고리(960=게임 서버 개발자) → 모르는 게임 스튜디오까지 자동 포착
#   - 등록(시드+사용자추가) 회사 → 회사 id 로 콕 조회(인접 기업·마케팅사 등 보강)
#  공고엔 작성일이 없어 store 의 first_seen(수집 시각)을 날짜로 쓴다.
# ════════════════════════════════════════════════════════════

WANTED_NAV = "https://www.wanted.co.kr/api/chaos/navigation/v1/results"
WANTED_SEARCH = "https://www.wanted.co.kr/api/chaos/search/v1/results"
WANTED_COMPANY_JOBS = "https://www.wanted.co.kr/api/v4/companies/{cid}/jobs"
WANTED_JOB_URL = "https://www.wanted.co.kr/wd/{jid}"
WANTED_COMPANY_URL = "https://www.wanted.co.kr/company/{cid}"

# 원티드 게임 직군 카테고리 id (959 게임 제작 / 960 게임 서버 개발자 / 961 클라)
WANTED_GAME_SERVER_JOB_ID = 960

# 등록 회사 공고 중 AWS 영업 관련 직무만 남길 키워드
JOB_ROLE_KEYWORDS = [
    "서버", "백엔드", "back-end", "backend", "인프라", "infra",
    "devops", "데브옵스", "sre", "클라우드", "cloud",
    "플랫폼", "platform", "시스템", "system",
]


_ssl_warned = False


def _jobs_get(url: str, params: dict | None = None):
    """채용 API 요청. 사내망 인증서 문제(SSL) 시 검증을 끄고 재시도한다."""
    global _ssl_warned
    try:
        return requests.get(url, headers=HEADERS, params=params, timeout=12)
    except requests.exceptions.SSLError:
        import urllib3
        urllib3.disable_warnings()
        if not _ssl_warned:
            print("[jobs] SSL 검증 실패 → verify=False 재시도 (사내망 인증서 추정)")
            _ssl_warned = True
        return requests.get(url, headers=HEADERS, params=params, timeout=12, verify=False)


def _skill_list(tags) -> list:
    out = []
    for t in tags or []:
        if isinstance(t, dict):
            out.append(t.get("title") or t.get("name") or "")
        elif isinstance(t, str):
            out.append(t)
    return [s for s in out if s]


def _addr_str(addr) -> str:
    if isinstance(addr, dict):
        return addr.get("location") or addr.get("full_location") or ""
    return addr or ""


def _is_relevant_role(title: str) -> bool:
    low = (title or "").lower()
    return any(k in low for k in JOB_ROLE_KEYWORDS)


def _wanted_job(it: dict, source: str = "원티드") -> dict:
    jid = it.get("id")
    comp = it.get("company") or {}
    return {
        "job_id": jid,
        "title": (it.get("position") or "").strip(),
        "company_raw": (comp.get("name") or "").strip(),
        "company_id": comp.get("id"),
        "link": WANTED_JOB_URL.format(jid=jid) if jid else "",
        "skills": _skill_list(it.get("skill_tags")),
        "address": _addr_str(it.get("address")),
        "annual_from": it.get("annual_from"),
        "annual_to": it.get("annual_to"),
        "source": source,
    }


def _fetch_wanted_game_jobs(max_items: int = 100) -> list:
    """원티드 게임 서버 개발자 카테고리 공고를 페이지네이션으로 수집."""
    items, offset = [], 0
    while offset < max_items:
        r = _jobs_get(WANTED_NAV, {
            "job_ids": WANTED_GAME_SERVER_JOB_ID,
            "country": "kr", "job_sort": "job.latest_order",
            "years": -1, "locations": "all", "limit": 20, "offset": offset,
        })
        try:
            data = r.json().get("data") or []
        except ValueError:
            data = []
        if not data:
            break
        items += [_wanted_job(it) for it in data]
        if len(data) < 20:
            break
        offset += 20
    return items


def _fetch_company_jobs(company_id) -> list:
    """등록 회사의 공고 중 영업 관련 직무만 가져온다."""
    r = _jobs_get(WANTED_COMPANY_JOBS.format(cid=company_id))
    try:
        data = r.json().get("data") or []  # 공고 없으면 data=null 로 옴
    except ValueError:
        data = []
    out = []
    for it in data:
        job = _wanted_job(it)
        if not job["link"]:  # company jobs 응답엔 id 가 없을 수 있음 → 회사 페이지로 대체
            job["link"] = WANTED_COMPANY_URL.format(cid=company_id)
        if _is_relevant_role(job["title"]):
            out.append(job)
    return out


def search_companies(query: str, limit: int = 10) -> list:
    """원티드 회사 검색 (회사 관리 UI의 '검색해서 추가'용)."""
    if not query.strip():
        return []
    r = _jobs_get(WANTED_SEARCH, {"query": query, "country": "kr", "limit": limit, "offset": 0})
    comps = (r.json().get("companies") or {}).get("data", [])
    return [{
        "id": c.get("id"),
        "name": c.get("name", ""),
        "industry": c.get("industry_name") or c.get("industry") or "",
    } for c in comps if c.get("name")]


# ── 회사명 정규화 + 별칭사전 (회사 단위 집계의 핵심) ─────────────
_LEGAL_RE = re.compile(
    r"(주식회사|유한회사|㈜|\(주\)|\(유\)|\(재\)|Inc\.?|Corp\.?|Co\.?,?\s*Ltd\.?|Ltd\.?|LLC)", re.I)
_PAREN_RE = re.compile(r"[\(（]([^)）]*)[\)）]")

# 같은 회사의 한글/영문/약칭 → 대표명. 알고리즘으론 못 잇는 한↔영을 사전으로 보강.
# (자회사는 일부러 분리 유지: 넥슨/넥슨게임즈/네오플은 각각 다른 영업 계정)
COMPANY_ALIASES = {
    "넥슨": ["nexon", "넥슨코리아"],
    "엔씨소프트": ["엔씨", "ncsoft"],
    "크래프톤": ["krafton"],
    "넷마블": ["netmarble"],
    "카카오게임즈": ["kakaogames"],
    "펄어비스": ["pearlabyss"],
    "스마일게이트": ["smilegate"],
    "컴투스": ["com2us"],
    "위메이드": ["wemade"],
    "데브시스터즈": ["devsisters"],
    "웹젠": ["webzen"],
    "네오위즈": ["neowiz"],
    "그라비티": ["gravity"],
    "시프트업": ["shiftup"],
    "넵튠": ["neptune"],
    "라인게임즈": ["linegames"],
}


def _norm_key(name: str):
    """회사명 비교용 정규화 키와 부수 별칭(괄호 안 영문 등)을 반환."""
    if not name:
        return "", []
    s = unicodedata.normalize("NFKC", name).strip()
    aliases = [a.strip() for a in _PAREN_RE.findall(s) if a.strip()]
    s = _PAREN_RE.sub(" ", s)
    s = _LEGAL_RE.sub(" ", s)
    s = re.sub(r"\s+", "", s)
    return s.casefold(), [a.casefold() for a in aliases]


# 별칭(정규화) → 대표명 역인덱스
_ALIAS_TO_CANON: dict = {}
for _canon, _variants in COMPANY_ALIASES.items():
    _ck, _ = _norm_key(_canon)
    _ALIAS_TO_CANON[_ck] = _canon
    for _v in _variants:
        _vk, _ = _norm_key(_v)
        _ALIAS_TO_CANON[_vk] = _canon


def _canonical_company(name: str):
    """(표시용 대표명, 집계 키)를 반환. 사전에 없으면 합치지 않는다(오합치 방지)."""
    key, aliases = _norm_key(name)
    for k in [key] + aliases:
        if k in _ALIAS_TO_CANON:
            canon = _ALIAS_TO_CANON[k]
            ck, _ = _norm_key(canon)
            return canon, ck
    return name.strip(), key


def resolve_tier(company_name: str) -> int:
    """회사 등급 결정. 우선순위: 수동 override > 큐레이트 키워드 목록 > 국민연금 직원수 > 소형.
    유명 회사는 키워드 목록이, 무명 스튜디오는 국민연금 직원수가 분류한다."""
    disp, key = _canonical_company(company_name)
    overrides = store.get_tier_overrides()
    if key in overrides and overrides[key] in (1, 2, 3):
        return overrides[key]
    kw = _company_tier(disp)
    if kw in (1, 2):  # 큐레이트 목록에 대형/중형으로 있으면 그걸 신뢰
        return kw
    cache = store.get_nps_cache()
    emp = cache.get(key, {}).get("employees")
    if emp is not None:
        return nps.classify_employees(emp)
    return 3


def aggregate_jobs(jobs: list) -> list:
    """공고 리스트를 회사 단위로 묶는다. 같은 회사가 여러 소스/공고로 와도 한 묶음.
    (등급/직원수는 app 의 enrich 단계에서 채운다 — 네트워크 조회가 필요하므로)"""
    groups: dict = {}
    for j in jobs:
        disp, key = _canonical_company(j.get("company_raw", ""))
        if not key:
            continue
        g = groups.get(key)
        if not g:
            g = groups[key] = {"company": disp, "key": key,
                               "tier": _company_tier(disp), "employees": None,
                               "sources": set(), "jobs": []}
        g["sources"].add(j["source"])
        link = j.get("link", "")
        if not (link and any(x.get("link") == link for x in g["jobs"])):
            g["jobs"].append(j)
    out = []
    for g in groups.values():
        g["sources"] = sorted(g["sources"])
        g["count"] = len(g["jobs"])
        out.append(g)
    out.sort(key=lambda g: (g["tier"], -g["count"]))
    return out


def crawl_jobs(extra_companies: list | None = None) -> list:
    """게임 직군 공고 + 등록 회사 공고를 모아 '원본 공고 리스트'를 반환한다.
    (저장소가 개별 공고를 보존·정리할 수 있도록 집계 전 단계를 돌려준다.
     화면 표시용 회사 단위 집계는 aggregate_jobs 로 읽을 때 수행)"""
    jobs: list = []
    try:
        jobs += _fetch_wanted_game_jobs()
    except Exception as e:
        print(f"[jobs] 원티드 게임 직군 수집 실패: {e}")

    for c in (extra_companies or []):
        cid = c.get("company_id") or c.get("id")
        if not cid and c.get("name"):  # 이름만 등록된 경우 검색으로 id 해소
            try:
                found = search_companies(c["name"], 1)
                cid = found[0]["id"] if found else None
            except Exception:
                cid = None
        if cid:
            try:
                jobs += _fetch_company_jobs(cid)
            except Exception as e:
                print(f"[jobs] 회사({cid}) 공고 수집 실패: {e}")
    return jobs


# ════════════════════════════════════════════════════════════
#  게임사 디렉토리 — 국민연금 "게임 소프트웨어" 업종코드로 일괄 수집
#  - 이름으로 한 곳씩 찾지 않고 업종코드로 긁어 오므로 동명회사·건설사
#    노이즈가 없고, 비상장 소형 스튜디오까지 직원수와 함께 들어온다.
#  - 직원수 외에 성장세(순증채용)·급여규모도 같은 행에서 얻는다.
# ════════════════════════════════════════════════════════════

# 게임 소프트웨어 개발 및 공급업 업종코드 (722000 응용SW는 너무 넓어 제외)
GAME_INDUSTRY_CODES = [722001, 722002, 722003]


def _region(addr: str) -> str:
    """'서울특별시 강남구 역삼동' → '서울 강남구'. 시도 약칭 + 시군구."""
    parts = (addr or "").split()
    if not parts:
        return ""
    sido = parts[0]
    for long, short in (("특별자치도", ""), ("특별자치시", ""), ("특별시", ""),
                        ("광역시", ""), ("자치도", ""), ("도", "")):
        if sido.endswith(long):
            sido = sido[: -len(long)] if long else sido
            break
    sgg = parts[1] if len(parts) > 1 else ""
    return f"{sido} {sgg}".strip()


def crawl_game_companies() -> list:
    """국민연금 게임 업종코드로 게임사를 일괄 수집한다.
    반환: [{company, key, employees, net_hire, payroll, region, industry, biz_no}]
    같은 회사(정규화 키)가 여러 사업장으로 와도 직원수 최대인 사업장 하나로 합친다.
    국민연금 키가 없으면 빈 리스트."""
    if not nps.has_key():
        return []
    by_key: dict = {}
    for code in GAME_INDUSTRY_CODES:
        page = 1
        while page <= 20:  # 코드당 최대 20,000행 (안전 상한)
            r = nps._get({"cond[사업장업종코드::EQ]": code, "perPage": 1000, "page": page})
            try:
                rows = r.json().get("data") or []
            except ValueError:
                break
            if not rows:
                break
            for x in rows:
                name = (x.get("사업장명") or "").strip()
                if not name:
                    continue
                # 가입상태 탈퇴(2) 사업장은 제외
                if x.get("사업장가입상태코드 1 등록 2 탈퇴") == 2:
                    continue
                emp = x.get("가입자수") or 0
                disp, key = _canonical_company(name)
                rec = {
                    "company": name,
                    "key": key,
                    "employees": int(emp),
                    "net_hire": int(x.get("신규취득자수") or 0) - int(x.get("상실가입자수") or 0),
                    "payroll": int(x.get("당월고지금액") or 0),
                    "region": _region(x.get("사업장지번상세주소") or x.get("사업장도로명상세주소") or ""),
                    "industry": x.get("사업장업종코드명") or "",
                    "biz_no": x.get("사업자등록번호"),
                }
                prev = by_key.get(key)
                if prev is None or rec["employees"] > prev["employees"]:
                    by_key[key] = rec
            if len(rows) < 1000:
                break
            page += 1
    return list(by_key.values())
