# Game Pulse — 게임 뉴스 & 트렌드 크롤러

글로벌·한국·AWS·K-GMA 등록 매체에서 게임 관련 뉴스와 정보를 한 화면에 모아 보여주는 Flask 기반 웹 대시보드입니다.

## 주요 기능

- **다중 소스 크롤링** — 18개 매체에서 RSS / HTML 스크래핑으로 수집
- **카테고리 필터** — 글로벌 / 한국 / AWS / 매체
- **카드 클릭 → 모달** — 요약, 소스, 날짜, 원문 보기 버튼
- **자동 번역** — 영문 기사는 모달 열람 시 한국어로 번역 (Google Translate)
- **번역 캐시** — 디스크 캐시로 재열람 시 즉시 표시
- **기업 규모 정렬** — 게임사 티어(Tier 1/2/3)로 정렬
- **e스포츠 자동 제외** — 키워드 기반 필터링
- **누적 저장(JSON)** — 수집한 기사를 `articles.json`에 link 기준으로 누적 → 피드에서 밀려나도 사라지지 않음
- **실제 작성일 파싱** — RSS published 날짜 + HTML 매체는 상세 페이지에서 작성일 추출(JSON-LD/meta/`<time>`)
- **5일 보존** — 수집 후 5일이 지난 기사는 자동 삭제 (수집 시각 기준)
- **북마크** — 북마크한 기사는 5일이 지나도 영구 보존, 북마크 필터 제공
- **10분 캐시** — 외부 사이트 부하 최소화 (새로고침 버튼은 항상 재크롤)

## 수집 소스

### 글로벌
GameSpot · IGN · Polygon · Kotaku · Eurogamer

### 한국
GameMeca

### AWS (게임 관련)
AWS Game Tech Blog · AWS News Blog (게임 키워드 필터)

### 매체 (K-GMA 등록)
**RSS**: PNN · 게임어바웃 · 게임톡 · 게임뷰 · 게임인사이트 · 게임플 · 경향게임스 · 뉴스앤게임(ZDNet)
**HTML 스크래핑**: 게임동아 · 매경게임진 · 데일리게임 · 게임포커스

## 설치 및 실행

### 요구사항
- Python 3.9+

### 설치
```bash
pip install -r requirements.txt
```

### 실행
```bash
python app.py
```

브라우저에서 http://127.0.0.1:5000/ 접속

## API 엔드포인트

- `GET /` — 메인 페이지 (쿼리: `?sort=date|tier`)
- `GET /api/news` — JSON 응답 (쿼리: `?category=...&source=...&sort=...`)
- `GET /api/refresh` — 캐시 무효화 후 재크롤
- `POST /api/translate` — `{title, summary}` 한국어 번역
- `POST /api/bookmark` — `{link, bookmarked}` 북마크 토글 (보존 대상 지정)

## 프로젝트 구조

```
game-news-crawler/
├── app.py              # Flask 라우트 (북마크 API 포함)
├── crawler.py          # 크롤러 + 작성일 파싱 + e스포츠 필터 + 기업 티어 + 정렬
├── store.py            # JSON 누적 저장 + 5일 보존 + 북마크
├── translator.py       # 번역 + 디스크 캐시
├── articles.json       # 누적 저장된 기사 (GitHub 함께 커밋)
├── requirements.txt
├── templates/
│   └── index.html      # 카드 그리드 + 모달 UI + 북마크
├── static/
│   └── style.css       # 미니멀 디자인
└── .gitignore
```

## 커스터마이징

- **소스 추가/제거**: `crawler.py` 의 `SOURCES` (RSS) 또는 `HTML_OUTLETS` (HTML)
- **기업 티어**: `crawler.py:COMPANY_TIERS` 딕셔너리
- **e스포츠 키워드**: `crawler.py:ESPORTS_KEYWORDS` 리스트
- **캐시 TTL**: `crawler.py:CACHE_TTL` (기본 600초)
- **보존 기간**: `store.py:RETENTION_DAYS` (기본 5일, 북마크는 예외)
- **HTML 작성일 신뢰 범위**: `crawler.py:_HTML_DATE_MAX_AGE_DAYS` (기본 30일, 초과 시 수집 시각 사용)
