#!/usr/bin/env python3
"""네이버 '복재성' 검색 결과 순위 체커"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import time
import logging
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

QUERY = "복재성"
KST = timezone(timedelta(hours=9))
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
HISTORY_CSV = os.path.join(RESULTS_DIR, "history.csv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def fetch_page(session: requests.Session, url: str, params: dict) -> str:
    for attempt in range(3):
        try:
            resp = session.get(url, params=params, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            log.warning("attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError("모든 재시도 실패")


def determine_type(url: str, classes: str) -> str:
    url_lower = url.lower()
    if "blog.naver" in url_lower or "blog" in classes:
        return "블로그"
    if "cafe.naver" in url_lower or "cafe" in classes:
        return "카페"
    if "kin.naver" in url_lower or "kin" in classes:
        return "지식iN"
    if "news" in url_lower or "news" in classes:
        return "뉴스"
    if "post.naver" in url_lower:
        return "포스트"
    return "웹문서"


def parse_integrated(html: str) -> list[dict]:
    """통합검색 결과 파싱"""
    soup = BeautifulSoup(html, "lxml")
    results = []
    rank = 1
    seen = set()

    main = soup.find(id="main_pack") or soup.body or soup

    # 각 섹션(블로그, 뉴스, 카페 등)의 개별 항목 추출
    # Naver의 현재 구조에 맞는 다중 셀렉터
    item_selectors = [
        ".lst_total > li",
        ".api_subject_bx .bx",
        ".total_area li",
        "section.sc_new li",
        "#section_blog li",
        "#section_news li",
        ".news_area li",
        ".blog_area li",
        ".cafe_area li",
        ".kin_area li",
        ".web_section li",
    ]

    title_selectors = [
        "a.link_tit",
        "a.total_tit",
        ".tit_wrap a",
        ".title_link",
        ".news_tit",
        "h2 > a",
        "h3 > a",
        ".api_txt_lines a",
    ]

    for sel in item_selectors:
        items = main.select(sel)
        if not items:
            continue
        for item in items:
            # 제목 링크 탐색
            link = None
            for ts in title_selectors:
                link = item.select_one(ts)
                if link:
                    break
            # 폴백: 충분히 긴 텍스트를 가진 첫 번째 a 태그
            if not link:
                for a in item.select("a"):
                    text = a.get_text(strip=True)
                    if len(text) > 5 and not text.startswith("http"):
                        link = a
                        break

            if not link:
                continue

            title = link.get_text(strip=True)
            url = link.get("href", "")

            if not title or not url or url in seen:
                continue
            seen.add(url)

            classes = " ".join(item.get("class", []))

            source_el = item.select_one(
                ".source, .sub_name, .user_info .id, "
                ".media_end_linked_more_point, .press_name"
            )
            source = source_el.get_text(strip=True) if source_el else ""

            snippet_el = item.select_one(
                ".dsc_txt, .total_dsc, .api_txt_lines, .desc, .sub_txt_wrap"
            )
            snippet = snippet_el.get_text(strip=True)[:300] if snippet_el else ""

            results.append(
                {
                    "rank": rank,
                    "type": determine_type(url, classes),
                    "title": title,
                    "url": url,
                    "source": source,
                    "snippet": snippet,
                }
            )
            rank += 1

    return results


def parse_blog_search(html: str) -> list[dict]:
    """블로그 검색 결과 파싱"""
    soup = BeautifulSoup(html, "lxml")
    results = []
    rank = 1

    items = soup.select(".lst_total > li, .list_type li, .blog_list li")
    for item in items:
        link = item.select_one("a.link_tit, a.title_link, .tit_wrap a, h3 a, h2 a")
        if not link:
            continue
        title = link.get_text(strip=True)
        url = link.get("href", "")
        if not title:
            continue

        author_el = item.select_one(".user_info .id, .sub_name, .blog_name")
        author = author_el.get_text(strip=True) if author_el else ""

        snippet_el = item.select_one(".dsc_txt, .desc, .sub_txt")
        snippet = snippet_el.get_text(strip=True)[:300] if snippet_el else ""

        date_el = item.select_one(".sub_txt.sub_date, .date")
        date_str = date_el.get_text(strip=True) if date_el else ""

        results.append(
            {
                "rank": rank,
                "type": "블로그",
                "title": title,
                "url": url,
                "source": author,
                "snippet": snippet,
                "date": date_str,
            }
        )
        rank += 1
    return results


def save_results(results: list[dict], timestamp: datetime) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    filename = timestamp.strftime("%Y-%m-%d_%H00") + ".json"
    filepath = os.path.join(RESULTS_DIR, filename)

    data = {
        "query": QUERY,
        "checked_at": timestamp.isoformat(),
        "total": len(results),
        "results": results,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("저장 완료: %s (%d건)", filepath, len(results))
    return filepath


def append_to_history(results: list[dict], timestamp: datetime) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    is_new = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["checked_at", "rank", "type", "title", "url", "source", "snippet"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        ts_str = timestamp.isoformat()
        for r in results:
            row = {
                "checked_at": ts_str,
                "rank": r.get("rank", ""),
                "type": r.get("type", ""),
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "source": r.get("source", ""),
                "snippet": r.get("snippet", "")[:150],
            }
            writer.writerow(row)


def run():
    now = datetime.now(KST)
    log.info("검색어: '%s' | 시각: %s", QUERY, now.strftime("%Y-%m-%d %H:%M KST"))

    session = requests.Session()

    # 1단계: 네이버 메인 방문 (쿠키 획득)
    try:
        session.get("https://www.naver.com/", headers=HEADERS, timeout=10)
        time.sleep(1)
    except Exception as e:
        log.warning("네이버 메인 접속 실패: %s", e)

    # 2단계: 통합검색
    integrated_results = []
    try:
        log.info("통합검색 크롤링 중...")
        html = fetch_page(
            session,
            "https://search.naver.com/search.naver",
            {"where": "nexearch", "query": QUERY},
        )
        integrated_results = parse_integrated(html)
        log.info("통합검색 결과: %d건", len(integrated_results))
    except Exception as e:
        log.error("통합검색 실패: %s", e)

    time.sleep(2)

    # 3단계: 블로그 검색 (통합검색에서 충분히 못 가져온 경우 보완)
    blog_results = []
    try:
        log.info("블로그 검색 크롤링 중...")
        html2 = fetch_page(
            session,
            "https://search.naver.com/search.naver",
            {"where": "blog", "query": QUERY},
        )
        blog_results = parse_blog_search(html2)
        log.info("블로그 검색 결과: %d건", len(blog_results))
    except Exception as e:
        log.error("블로그 검색 실패: %s", e)

    # 결과 병합 (통합 우선, 블로그로 보완)
    if integrated_results:
        final_results = integrated_results
    else:
        final_results = blog_results

    if not final_results:
        log.warning("수집된 결과가 없습니다. HTML 구조 확인 필요.")
        # 디버그용 HTML 저장
        debug_path = os.path.join(RESULTS_DIR, now.strftime("%Y-%m-%d_%H00") + "_debug.html")
        try:
            os.makedirs(RESULTS_DIR, exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html if 'html' in dir() else "no html")
            log.info("디버그 HTML 저장: %s", debug_path)
        except Exception:
            pass
        return

    save_results(final_results, now)
    append_to_history(final_results, now)

    # 콘솔 출력
    print(f"\n{'='*60}")
    print(f"네이버 '{QUERY}' 검색 순위 | {now.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"{'='*60}")
    for r in final_results[:20]:
        print(f"[{r['rank']:2d}] [{r['type']}] {r['title']}")
        if r.get("source"):
            print(f"      출처: {r['source']}")
        print(f"      URL: {r['url']}")
    print(f"{'='*60}")
    print(f"총 {len(final_results)}건 수집됨\n")


if __name__ == "__main__":
    run()
