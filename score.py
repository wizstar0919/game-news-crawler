"""게임사 AWS 영업 '타겟 점수' 계산.

직원수만으로는 영업 가치를 못 잡는다(직원 적어도 매출·성장 큰 회사가 있음).
4개 신호를 0~1 로 정규화해 가중합한 0~100 점수와 등급을 매긴다.

배점(합 100):
  서버·백엔드 채용 35  ← 인프라 확장 = AWS 직격 신호 (가장 높게)
  성장세(순증 채용) 25  ← 빠르게 크는 중
  매출/급여규모     25  ← 지출 여력
  직원수           15  ← 기본 체급

등급: 🔥핫 70+, 🟡관심 40~69, ⚪일반 그 미만.
"""

WEIGHTS = {"server_jobs": 35, "growth": 25, "money": 25, "size": 15}


def _band(value, thresholds) -> float:
    """value 가 속한 구간의 점수(0~1)를 반환. thresholds=[(상한, 점수), ...] 오름차순."""
    for limit, sub in thresholds:
        if value < limit:
            return sub
    return 1.0


def _size_score(employees: int) -> float:
    return _band(employees, [(10, 0.1), (30, 0.25), (50, 0.4),
                             (150, 0.6), (300, 0.8)])


def _growth_score(net_hire: int, employees: int) -> float:
    """순증 채용. 절대값과 직원 대비 증가율을 함께 본다."""
    if net_hire <= 0:
        return 0.0
    by_abs = _band(net_hire, [(3, 0.4), (6, 0.6), (16, 0.8)])
    rate = net_hire / employees if employees else 0
    by_rate = _band(rate, [(0.03, 0.3), (0.07, 0.6), (0.15, 0.85)])
    return max(by_abs, by_rate)


def _money_score(revenue, payroll: int) -> float:
    """매출(있으면 우선)로, 없으면 급여규모(당월고지금액, 원)로 자금 여력 추정."""
    if revenue:  # 단위: 원
        eok = revenue / 1e8
        return _band(eok, [(50, 0.3), (300, 0.5), (1000, 0.7), (5000, 0.9)])
    eok_m = (payroll or 0) / 1e8  # 월 고지금액(억/월)
    return _band(eok_m, [(0.3, 0.2), (1, 0.4), (3, 0.6), (10, 0.8)])


def _server_jobs_score(n: int) -> float:
    return _band(n, [(1, 0.0), (2, 0.5), (3, 0.7), (5, 0.85)])


def grade(score: int) -> str:
    if score >= 70:
        return "핫"
    if score >= 40:
        return "관심"
    return "일반"


def compute(company: dict) -> dict:
    """company 딕셔너리(employees, net_hire, payroll, revenue, server_jobs)에
    score/grade/breakdown 을 채워 돌려준다."""
    emp = company.get("employees") or 0
    subs = {
        "server_jobs": _server_jobs_score(company.get("server_jobs") or 0),
        "growth": _growth_score(company.get("net_hire") or 0, emp),
        "money": _money_score(company.get("revenue"), company.get("payroll") or 0),
        "size": _size_score(emp),
    }
    score = round(sum(WEIGHTS[k] * subs[k] for k in WEIGHTS))
    company["score"] = score
    company["grade"] = grade(score)
    company["breakdown"] = {k: round(WEIGHTS[k] * subs[k]) for k in WEIGHTS}
    return company
