# 네이버 "복재성" 키워드 검색 순위 추적기

네이버 통합검색에서 `복재성` 키워드로 검색했을 때 첫 화면에 노출되는 글(블로그/카페/뉴스/포스트 등)의
순위를 1시간마다 자동으로 기록하는 자동화입니다.

## 동작 방식

1. `.github/workflows/naver-ranking.yml` 워크플로가 **매시 정각(UTC 기준)** GitHub Actions에서 실행됩니다.
2. `scripts/track_naver_ranking.py` 스크립트가 네이버 통합검색 결과 페이지를 가져와,
   첫 화면에 노출되는 콘텐츠 링크를 등장 순서(=노출 순위) 그대로 최대 30개 추출합니다.
3. 결과가 아래 두 파일에 기록되고, 워크플로가 자동으로 커밋/푸시합니다.
   - `data/naver_ranking_latest.json` : 가장 최근 실행 결과 스냅샷
   - `data/naver_ranking_history.csv` : 실행 시각별 순위 누적 기록 (시계열 분석용)

## 로컬에서 수동 실행하기

```bash
pip install -r requirements.txt
python scripts/track_naver_ranking.py
```

다른 키워드로 실행하려면 환경변수를 지정하세요.

```bash
NAVER_KEYWORD="다른키워드" python scripts/track_naver_ranking.py
```

## 주의 사항 / 한계

- **예약 실행(cron)은 기본 브랜치(main)에 있는 워크플로에서만 동작합니다.** 이 브랜치의 PR이
  main에 머지되기 전까지는 `workflow_dispatch`(수동 실행)만 가능합니다.
- 네이버는 검색 결과 페이지의 HTML 구조를 예고 없이 바꿀 수 있습니다. 이 스크립트는 CSS 클래스명
  대신 결과 링크의 **도메인**(blog.naver.com, cafe.naver.com, news.naver.com 등)을 기준으로
  콘텐츠를 분류하므로 마크업 변경에 비교적 강하지만, 완전히 새로운 레이아웃으로 바뀌면 수정이
  필요할 수 있습니다.
- "첫 화면"은 화면 해상도에 따라 달라질 수 있어, 등장 순서 기준 상위 30개를 근사치로 사용합니다.
- 과도한 요청은 네이버 서버에 부담을 줄 수 있으므로 실행 주기(1시간)를 임의로 단축하지 않는 것을
  권장합니다.
