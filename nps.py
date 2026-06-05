"""국민연금 가입 사업장 내역 API 기반 직원수 조회 + 규모 자동 분류.

공공데이터포털(api.odcloud.kr)의 "국민연금 가입 사업장 내역" 월별 데이터에서
사업장명으로 회사를 찾아 가입자수(≈직원수)를 읽는다. 이 값으로 큐레이트 목록에
없는 무명 스튜디오까지 자동으로 대/중/소를 분류한다.

매칭 난점과 해법:
- LIKE 검색은 "넥슨화장품"처럼 무관한 회사도 잡힌다 → 업종(소프트웨어/IT)으로 거르고,
  이름이 정확히 일치하는 법인을 우선, 없으면 최대 가입자수 법인을 고른다.
- 본사·지사가 따로 등록돼 있어, 정확 일치(예: "(주)크래프톤")를 가장 신뢰한다.

키는 .env 의 NPS_API_KEY 에서 읽는다. 키가 없으면 조회는 None 을 반환(앱은 정상 동작).
"""

import os
import re
import requests
import urllib3

# 직원수(가입자수) 기준 규모 밴드 — 조정 가능
TIER_LARGE_MIN = 300   # 대형: 300명 이상
TIER_MID_MIN = 50      # 중형: 50~299명, 그 미만 소형

# 국민연금 가입 사업장 내역 (월별 파일 API). 가장 최신월 uddi.
# 직원수는 월별로 거의 안 변하므로 최신월 하나만 쓴다. 갱신하려면 아래만 교체.
NPS_BASE = "https://api.odcloud.kr/api/15083277/v1"
NPS_UDDI = "uddi:c9f9e0f9-0e4a-47b9-a2cb-e7502959eaa0"  # 2026-05

# 업종코드명에 이게 포함되면 IT/게임 계열로 본다 (화장품·건설·어린이집 등 배제)
_IT_KEYWORDS = ["소프트웨어", "정보", "게임", "인터넷", "컴퓨터", "온라인", "포털", "콘텐츠", "데이터"]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _load_key() -> str:
    """NPS_API_KEY 를 환경변수 또는 같은 폴더의 .env 에서 읽는다."""
    key = os.environ.get("NPS_API_KEY", "").strip()
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
                    if k.strip() == "NPS_API_KEY":
                        return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


NPS_API_KEY = _load_key()


def has_key() -> bool:
    return bool(NPS_API_KEY)


def _get(params: dict):
    url = f"{NPS_BASE}/{NPS_UDDI}"
    p = {"serviceKey": NPS_API_KEY, "page": 1, "perPage": 100}
    p.update(params)
    try:
        return requests.get(url, params=p, headers=_HEADERS, timeout=20)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings()
        return requests.get(url, params=p, headers=_HEADERS, timeout=20, verify=False)


def classify_employees(count) -> int:
    """가입자수 → 규모(1 대형 / 2 중형 / 3 소형)."""
    if count is None:
        return 3
    if count >= TIER_LARGE_MIN:
        return 1
    if count >= TIER_MID_MIN:
        return 2
    return 3


def lookup_employees(name: str):
    """사업장명으로 직원수를 조회한다. (가입자수, 매칭된 사업장명) 또는 None.
    업종(IT) 필터 + 정확 일치 우선 + 최대 가입자수 선택."""
    name = (name or "").strip()
    if not name or not NPS_API_KEY:
        return None
    # LIKE 검색어는 괄호(영문 별칭) 등을 떼고 한글 브랜드만 사용
    # 예: "베이글코드(Bagelcode)" → "베이글코드"
    search = re.sub(r"[\(（].*?[\)）]", "", name).strip() or name
    try:
        r = _get({"cond[사업장명::LIKE]": search})
        if r.status_code != 200:
            return None
        rows = r.json().get("data") or []
    except Exception:
        return None
    if not rows:
        return None

    # 업종이 IT/게임 계열인 것만 (없으면 전체에서)
    it_rows = [x for x in rows
               if any(k in (x.get("사업장업종코드명") or "") for k in _IT_KEYWORDS)] or rows

    from crawler import _norm_key  # 회사명 정규화 재사용 (지연 임포트로 순환참조 방지)
    brand, _ = _norm_key(name)

    def nk(x):
        return _norm_key(x.get("사업장명", ""))[0]

    exact = [x for x in it_rows if nk(x) == brand]
    prefix = [x for x in it_rows if nk(x).startswith(brand)]
    pool = exact or prefix or it_rows
    best = max(pool, key=lambda x: x.get("가입자수") or 0)
    cnt = best.get("가입자수")
    if cnt is None:
        return None
    return int(cnt), best.get("사업장명", "")
