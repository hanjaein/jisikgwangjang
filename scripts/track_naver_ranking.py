#!/usr/bin/env python3
"""
네이버 통합검색에서 지정한 키워드로 검색했을 때
첫 화면에 노출되는 글(블로그/카페/뉴스/포스트 등)의 순위를 기록하는 스크립트.

매 실행마다:
1. 네이버 통합검색 결과 페이지를 가져온다.
2. 첫 화면에 노출되는 콘텐츠 링크를 등장 순서(=노출 순위) 그대로 추출한다.
3. data/naver_ranking_latest.json 에 이번 결과를 저장한다.
4. data/naver_ranking_history.csv 에 이번 결과를 누적 기록한다.

GitHub Actions에서 1시간마다(cron) 실행되도록 설계되었다.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

KEYWORD = os.environ.get("NAVER_KEYWORD", "복재성")
MAX_RANK = int(os.environ.get("NAVER_MAX_RANK", "30"))  # 첫 화면으로 간주할 최대 노출 개수
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LATEST_JSON_PATH = os.path.join(DATA_DIR, "naver_ranking_latest.json")
HISTORY_CSV_PATH = os.path.join(DATA_DIR, "naver_ranking_history.csv")

SEARCH_URL = "https://search.naver.com/search.naver"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# 결과 링크의 도메인을 사람이 읽기 쉬운 콘텐츠 유형으로 분류한다.
# 네이버는 HTML 클래스명을 자주 바꾸므로, 비교적 안정적인 "링크 도메인" 기준으로 분류한다.
DOMAIN_TYPE_RULES: list[tuple[str, str]] = [
    ("blog.naver.com", "블로그"),
    ("m.blog.naver.com", "블로그"),
    ("cafe.naver.com", "카페"),
    ("m.cafe.naver.com", "카페"),
    ("post.naver.com", "포스트"),
    ("m.post.naver.com", "포스트"),
    ("news.naver.com", "뉴스"),
    ("n.news.naver.com", "뉴스"),
    ("m.news.naver.com", "뉴스"),
    ("in.naver.com", "인플루언서"),
    ("tv.naver.com", "네이버TV"),
    ("kin.naver.com", "지식iN"),
    ("m.kin.naver.com", "지식iN"),
    ("shopping.naver.com", "쇼핑"),
    ("book.naver.com", "책"),
    ("map.naver.com", "지도/플레이스"),
    ("terms.naver.com", "지식백과"),
]

# 검색결과 본문이 아닌 UI/광고/네비게이션 링크를 걸러내기 위한 키워드.
EXCLUDE_HREF_SUBSTRINGS = [
    "ader.naver.com",
    "adcr.naver.com",
    "search.naver.com/search.naver",  # 관련검색어, 다른 탭 링크 등 내부 검색 링크
    "javascript:",
    "#",
]
EXCLUDE_TEXTS = {
    "", "더보기", "더 보기", "이전", "다음", "신고", "펼치기", "접기",
    "홈", "블로그", "카페", "뉴스", "이미지", "지식iN", "동영상", "쇼핑",
}


@dataclass
class RankedItem:
    rank: int
    type: str
    title: str
    url: str


def fetch_search_html(keyword: str) -> str:
    params = {
        "where": "nexearch",
        "sm": "top_hty",
        "fbm": "0",
        "ie": "utf8",
        "query": keyword,
    }
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                SEARCH_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:  # pragma: no cover - 네트워크 예외
            last_error = exc
            wait = 2 * attempt
            print(f"[경고] 요청 실패({attempt}/{MAX_RETRIES}): {exc} - {wait}초 후 재시도", file=sys.stderr)
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def classify_type(url: str) -> str | None:
    """검색결과 성격의 링크가 아니면 None을 반환한다."""
    host = urlparse(url).netloc.lower()
    for domain, label in DOMAIN_TYPE_RULES:
        if host == domain or host.endswith("." + domain):
            return label
    return None


def should_exclude(href: str, text: str) -> bool:
    if not href.startswith("http"):
        return True
    for bad in EXCLUDE_HREF_SUBSTRINGS:
        if bad in href:
            return True
    if text.strip() in EXCLUDE_TEXTS:
        return True
    return False


def extract_title(anchor) -> str:
    text = anchor.get_text(" ", strip=True)
    if text:
        return text
    # 앵커 자체에 텍스트가 없으면 near 자손(strong/span 등)을 찾아본다.
    for child in anchor.find_all(True):
        child_text = child.get_text(" ", strip=True)
        if child_text:
            return child_text
    return ""


def parse_ranking(html: str, max_rank: int) -> list[RankedItem]:
    soup = BeautifulSoup(html, "lxml")

    main = soup.select_one("#main_pack") or soup

    items: list[RankedItem] = []
    seen_urls: set[str] = set()

    for anchor in main.find_all("a", href=True):
        href = anchor["href"]
        title = extract_title(anchor)

        if should_exclude(href, title):
            continue

        content_type = classify_type(href)
        if content_type is None:
            continue

        # 정규화: 추적 파라미터 등을 제거해 같은 글이 중복 집계되지 않도록 한다.
        parsed = urlparse(href)
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            # 게시글 식별에 필요한 핵심 쿼리(logNo 등)는 남긴다.
            keep_keys = {"logNo", "articleid", "artid", "no", "boardid"}
            kept = {k: v for k, v in parse_qs(parsed.query).items() if k in keep_keys}
            if kept:
                query_str = "&".join(f"{k}={v[0]}" for k, v in sorted(kept.items()))
                normalized_url = f"{normalized_url}?{query_str}"

        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        items.append(
            RankedItem(
                rank=len(items) + 1,
                type=content_type,
                title=title,
                url=normalized_url,
            )
        )

        if len(items) >= max_rank:
            break

    return items


def save_latest_json(keyword: str, timestamp: str, items: list[RankedItem]) -> None:
    payload = {
        "keyword": keyword,
        "checked_at": timestamp,
        "count": len(items),
        "items": [asdict(item) for item in items],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_history_csv(keyword: str, timestamp: str, items: list[RankedItem]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.isfile(HISTORY_CSV_PATH)
    with open(HISTORY_CSV_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["checked_at", "keyword", "rank", "type", "title", "url"])
        if items:
            for item in items:
                writer.writerow([timestamp, keyword, item.rank, item.type, item.title, item.url])
        else:
            # 검색 결과를 하나도 못 찾은 경우에도 기록을 남겨 추적 공백을 알 수 있게 한다.
            writer.writerow([timestamp, keyword, "", "", "(검색결과 없음/파싱 실패)", ""])


def main() -> int:
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    try:
        html = fetch_search_html(KEYWORD)
    except requests.RequestException as exc:
        print(f"[오류] 네이버 검색 페이지를 가져오지 못했습니다: {exc}", file=sys.stderr)
        return 1

    items = parse_ranking(html, MAX_RANK)

    if not items:
        print("[경고] 검색 결과를 파싱하지 못했습니다. 네이버 페이지 구조가 변경되었을 수 있습니다.", file=sys.stderr)

    save_latest_json(KEYWORD, timestamp, items)
    append_history_csv(KEYWORD, timestamp, items)

    print(f"[완료] '{KEYWORD}' 검색 순위 {len(items)}건 기록 ({timestamp})")
    for item in items:
        print(f"  {item.rank:>2}. [{item.type}] {item.title} - {item.url}")

    return 0 if items else 2


if __name__ == "__main__":
    sys.exit(main())
