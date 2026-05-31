# CLAUDE.md

이 파일은 Claude Code가 이 저장소에서 작업할 때 참고하는 프로젝트 안내문입니다.

## 프로젝트 개요

**Game Pulse** — 게임 뉴스 & 트렌드 크롤러. 여러 매체(글로벌·한국·AWS·K-GMA)에서 게임 관련 뉴스를 모아 한 화면에 보여주는 Flask 기반 웹 대시보드.

- 언어/프레임워크: Python 3.9+, Flask 3
- 주요 라이브러리: feedparser(RSS), requests, beautifulsoup4(HTML 스크래핑), deep-translator(번역)

## 실행 방법

```bash
pip install -r requirements.txt
python app.py
```

→ 브라우저에서 http://127.0.0.1:5000 접속.

⚠️ **첫 접속은 10~15초 느립니다** — 18개 매체를 처음 크롤링하기 때문. 이후엔 캐시(10분)로 빨라짐. "접속 안 됨"이 아니라 로딩 중이니 기다릴 것.

## 파일 구조

| 파일 | 역할 |
|------|------|
| `app.py` | Flask 라우트 (`/`, `/api/news`, `/api/refresh`, `/api/bookmark`, `/api/bookmarks`, `/api/translate`) |
| `crawler.py` | 크롤링 + 작성일 파싱 + e스포츠 필터 + 게임사 규모(티어) + 정렬 (가장 핵심) |
| `store.py` | JSON 누적 저장 + 5일 보존 + 사용자별 북마크 |
| `translator.py` | 번역 + 디스크 캐시 |
| `articles.json` | 누적 저장된 기사 (**GitHub 커밋 대상**) |
| `user_bookmarks.json` | 코드별 북마크 (자동 생성, **.gitignore — 커밋 안 함**) |
| `templates/index.html` | 카드 그리드 + 모달 + 필터 UI + 클라이언트 측 북마크 JS |
| `static/style.css` | 스타일 |

## 핵심 동작과 규칙 (수정 시 주의)

- **게임사 규모 필터**: `crawler.py:COMPANY_TIERS` 의 회사명으로 기사를 대형(1)/중형(2)/소형(3)으로 분류. 1·2 목록에 없으면 모두 소형(3). UI에서 카테고리 필터와 AND로 동작. 회사를 대형/중형으로 분류하려면 이 딕셔너리에 이름만 추가.
- **사용자별 북마크**: 사용자가 입력한 "코드"(별명)별로 분리 저장. `user_bookmarks.json` 에 `{코드: [link, ...]}` 구조. 코드는 브라우저 localStorage(`gp_user_code`)에 기억되지만 북마크 내용은 서버 보관 → 기기 간 동기화됨. 비밀번호 없음(소규모 내부용). `POST /api/bookmark` 는 `code` 필수.
- **보존(prune)**: 수집 시각(first_seen) 기준 `store.py:RETENTION_DAYS`(기본 5일) 지나면 삭제. 단 **누구든 북마크한 기사는 보존**.
- **e스포츠 자동 제외**: `crawler.py:ESPORTS_KEYWORDS` 키워드로 필터링.
- **HTML 매체 작성일**: 상세 페이지에서 JSON-LD/meta/`<time>` 파싱. 신뢰 범위 `_HTML_DATE_MAX_AGE_DAYS`(기본 30일) 초과/미래면 수집 시각으로 대체.
- **캐시**: `crawler.py:CACHE_TTL`(기본 600초). 화면 데이터는 항상 store에서 읽으므로 북마크 변경은 즉시 반영, 재크롤 여부만 캐시가 판단.

## Git / 배포

- 원격: https://github.com/wizstar0919/game-news-crawler (기본 브랜치 `main`)
- `user_bookmarks.json` 은 코드+개인 관심기사가 들어가므로 절대 커밋하지 않음(.gitignore에 등록됨).
- 아직 인터넷에 배포되지 않음 — 현재는 localhost 전용. 배포 시 Render 등 파이썬 실행 가능한 호스팅 필요(GitHub Pages는 정적이라 불가).

## 작업 스타일 메모

- 사용자는 한국어로 소통. 답변은 한국어로.
- 코드 작성·제작을 시작하기 전에 먼저 "만들까요?"를 묻고 동의를 받은 뒤 진행할 것.
