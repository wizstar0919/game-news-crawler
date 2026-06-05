"""DART 전자공시(opendart.fss.or.kr) 기반 매출 조회.

상장·외감사 대상 법인의 사업보고서에서 매출액을 읽어 "지출 여력" 신호로 쓴다.
국민연금 직원수와 달리 매출은 회사 규모를 자금 측면에서 보여주므로,
직원 적어도 매출/성장 큰 회사(예: 넥써쓰)를 타겟 점수에서 끌어올린다.

매칭 방식:
- DART 는 회사명이 깔끔한 법정 법인명이라(국민연금의 건설사·동명회사 노이즈 없음)
  정규화한 이름으로 정확 일치시키면 신뢰도가 높다.
- 회사코드(corp_code) 전체 목록을 받아 한 번 인덱싱해두고(디스크 캐시),
  이후엔 이름→코드→매출 순으로 조회한다.

키는 .env 의 DART_API_KEY 에서 읽는다. 키가 없으면 조회는 None 을 반환(앱은 정상 동작).
"""

import io
import os
import zipfile
import requests
import urllib3
import xml.etree.ElementTree as ET

BASE = "https://opendart.fss.or.kr/api"
CORP_INDEX_PATH = os.path.join(os.path.dirname(__file__), "dart_corp.json")
# 사업보고서(11011) 기준, 최신 연도부터 거슬러 시도 (당해 보고서는 보통 3월경 공시)
REPRT_CODE = "11011"
TRY_YEARS = ["2025", "2024", "2023"]
# 매출 계정명 (재무제표 표기 차이 대응)
_REVENUE_NAMES = ("매출액", "수익(매출액)", "영업수익")

# DART 법정 법인명이 흔한 호칭과 달라 이름 매칭이 안 되는 회사 보정.
#   {정규화 입력키: DART corp_code}. (예: 엔씨소프트는 DART 법인명이 "NC")
# 새 사례가 생기면 corp_code 만 추가하면 된다.
_CORP_OVERRIDE = {
    "엔씨소프트": "00261443",  # DART 법인명 "NC" (종목 036570)
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _load_key() -> str:
    """DART_API_KEY 를 환경변수 또는 같은 폴더의 .env 에서 읽는다."""
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == "DART_API_KEY":
                        return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


DART_API_KEY = _load_key()


def has_key() -> bool:
    return bool(DART_API_KEY)


def _get(path: str, params: dict, want_json: bool = True):
    """DART API 요청. 사내망/윈도우 인증서 문제(SSL) 시 검증을 끄고 재시도."""
    url = f"{BASE}/{path}"
    p = {"crtfc_key": DART_API_KEY}
    p.update(params)
    try:
        return requests.get(url, params=p, headers=_HEADERS, timeout=30)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings()
        return requests.get(url, params=p, headers=_HEADERS, timeout=30, verify=False)


# ── 회사코드 인덱스 (이름 정규화 → corp_code, stock_code) ──────────
_index_mem = None  # 프로세스 메모리 캐시


def _build_corp_index() -> dict:
    """DART 전체 회사코드 목록(zip)을 받아 {정규화이름: {corp_code, stock_code, name}} 로 인덱싱.
    같은 이름이 여러 개면 상장사(stock_code 있는 쪽)를 우선한다."""
    from crawler import _norm_key  # 회사명 정규화 재사용 (지연 임포트로 순환참조 방지)
    r = _get("corpCode.xml", {})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read(z.namelist()[0]).decode("utf-8"))
    index: dict = {}
    for el in root.iter("list"):
        name = (el.findtext("corp_name") or "").strip()
        if not name:
            continue
        key, _ = _norm_key(name)
        if not key:
            continue
        stock = (el.findtext("stock_code") or "").strip()
        rec = {"corp_code": el.findtext("corp_code"), "stock_code": stock, "name": name}
        prev = index.get(key)
        # 상장사 우선: 기존이 비상장이고 지금이 상장이면 교체
        if prev is None or (not prev.get("stock_code") and stock):
            index[key] = rec
    return index


def _load_index() -> dict:
    """회사코드 인덱스를 메모리→디스크→DART 순으로 로드한다."""
    global _index_mem
    if _index_mem is not None:
        return _index_mem
    if os.path.exists(CORP_INDEX_PATH):
        try:
            with open(CORP_INDEX_PATH, "r", encoding="utf-8") as f:
                import json
                _index_mem = json.load(f)
                return _index_mem
        except (OSError, ValueError):
            pass
    if not DART_API_KEY:
        _index_mem = {}
        return _index_mem
    try:
        idx = _build_corp_index()
    except Exception:
        idx = {}
    if idx:
        try:
            import json
            tmp = CORP_INDEX_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False)
            os.replace(tmp, CORP_INDEX_PATH)
        except OSError:
            pass
    _index_mem = idx
    return idx


def _parse_amount(s) -> int | None:
    """'36,722,406,111' → 36722406111. 음수/괄호도 처리."""
    if s in (None, "", "-"):
        return None
    s = str(s).strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = int(float(s))
        return -v if neg else v
    except ValueError:
        return None


def _fetch_revenue(corp_code: str):
    """corp_code 의 최신 사업보고서에서 매출액을 읽는다. (매출, 연도) 또는 None.
    재무제표(개별/별도) 우선, 없으면 연결."""
    for year in TRY_YEARS:
        r = _get("fnlttSinglAcnt.json",
                 {"corp_code": corp_code, "bsns_year": year, "reprt_code": REPRT_CODE})
        try:
            j = r.json()
        except ValueError:
            continue
        if j.get("status") != "000":
            continue
        rows = [x for x in (j.get("list") or [])
                if x.get("account_nm") in _REVENUE_NAMES]
        if not rows:
            continue
        # 재무제표(OFS, 개별/별도) 우선, 없으면 첫 행
        pick = next((x for x in rows if x.get("fs_div") == "OFS"), rows[0])
        amt = _parse_amount(pick.get("thstrm_amount"))
        if amt is not None:
            return amt, year
    return None


def lookup_revenue(company_name: str):
    """회사명으로 최신 매출을 조회한다. (매출, 연도, 매칭법인명, 상장코드) 또는 None.
    상장·외감사가 아니면(=DART 미공시) None."""
    name = (company_name or "").strip()
    if not name or not DART_API_KEY:
        return None
    from crawler import _norm_key
    key, _ = _norm_key(name)
    if key in _CORP_OVERRIDE:
        rec = {"corp_code": _CORP_OVERRIDE[key], "name": name, "stock_code": ""}
    else:
        rec = _load_index().get(key)
    if not rec:
        return None
    res = _fetch_revenue(rec["corp_code"])
    if not res:
        return None
    revenue, year = res
    return revenue, year, rec.get("name", ""), rec.get("stock_code", "")
