#!/usr/bin/env python3
"""네이버 '복재성' 검색 결과 순위 체커 + 변화 시 이메일 알림"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import time
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from glob import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

QUERY = "복재성"
KST = timezone(timedelta(hours=9))
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
HISTORY_CSV = os.path.join(RESULTS_DIR, "history.csv")
NOTIFY_EMAIL = "0@thesaveworld.org"

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


# ──────────────────────────────────────────────
# 네트워크
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# 파싱
# ──────────────────────────────────────────────

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
            link = None
            for ts in title_selectors:
                link = item.select_one(ts)
                if link:
                    break
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

            results.append({
                "rank": rank,
                "type": determine_type(url, classes),
                "title": title,
                "url": url,
                "source": source,
                "snippet": snippet,
            })
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

        results.append({
            "rank": rank,
            "type": "블로그",
            "title": title,
            "url": url,
            "source": author,
            "snippet": snippet,
            "date": date_str,
        })
        rank += 1
    return results


# ──────────────────────────────────────────────
# 저장
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# 순위 변화 감지
# ──────────────────────────────────────────────

def load_previous_results() -> list[dict] | None:
    """results/ 폴더에서 가장 최근 JSON 파일 로드"""
    files = sorted(glob(os.path.join(RESULTS_DIR, "????-??-??_?????.json")))
    # 현재 실행 파일은 제외 (아직 저장 전이므로 마지막 이전 파일)
    if len(files) < 1:
        return None
    # 마지막 파일 읽기
    path = files[-1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        log.info("이전 결과 로드: %s (%d건)", path, data.get("total", 0))
        return data.get("results", [])
    except Exception as e:
        log.warning("이전 결과 로드 실패: %s", e)
        return None


def detect_changes(prev: list[dict], curr: list[dict]) -> dict:
    """
    이전 결과와 현재 결과를 비교해 변화 목록 반환.
    URL을 기준으로 식별.
    """
    prev_by_url = {r["url"]: r for r in prev}
    curr_by_url = {r["url"]: r for r in curr}

    new_items = []       # 새로 등장
    removed_items = []   # 사라짐
    rank_changes = []    # 순위 변동

    for url, cr in curr_by_url.items():
        if url not in prev_by_url:
            new_items.append(cr)
        else:
            pr = prev_by_url[url]
            diff = pr["rank"] - cr["rank"]   # 양수 = 상승
            if diff != 0:
                rank_changes.append({
                    **cr,
                    "prev_rank": pr["rank"],
                    "rank_diff": diff,
                })

    for url, pr in prev_by_url.items():
        if url not in curr_by_url:
            removed_items.append(pr)

    return {
        "new": new_items,
        "removed": removed_items,
        "rank_changes": rank_changes,
        "has_changes": bool(new_items or removed_items or rank_changes),
    }


# ──────────────────────────────────────────────
# 이메일
# ──────────────────────────────────────────────

def build_email_html(changes: dict, curr: list[dict], timestamp: datetime) -> str:
    ts = timestamp.strftime("%Y-%m-%d %H:%M KST")

    def arrow(diff: int) -> str:
        if diff > 0:
            return f'<span style="color:#e53935">▲{diff}</span>'
        return f'<span style="color:#1e88e5">▼{abs(diff)}</span>'

    sections = []

    if changes["rank_changes"]:
        rows = ""
        for r in sorted(changes["rank_changes"], key=lambda x: x["rank"]):
            rows += (
                f"<tr>"
                f"<td>{r['prev_rank']}→<b>{r['rank']}</b></td>"
                f"<td>{arrow(r['rank_diff'])}</td>"
                f"<td>[{r['type']}] <a href='{r['url']}'>{r['title']}</a></td>"
                f"<td>{r.get('source','')}</td>"
                f"</tr>"
            )
        sections.append(
            f"<h3 style='color:#f57c00'>📊 순위 변동 ({len(changes['rank_changes'])}건)</h3>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
            f"<tr style='background:#fff3e0'><th>순위</th><th>변화</th><th>제목</th><th>출처</th></tr>"
            f"{rows}</table>"
        )

    if changes["new"]:
        rows = ""
        for r in changes["new"]:
            rows += (
                f"<tr>"
                f"<td><b>{r['rank']}</b></td>"
                f"<td>[{r['type']}] <a href='{r['url']}'>{r['title']}</a></td>"
                f"<td>{r.get('source','')}</td>"
                f"</tr>"
            )
        sections.append(
            f"<h3 style='color:#2e7d32'>🆕 신규 등장 ({len(changes['new'])}건)</h3>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
            f"<tr style='background:#e8f5e9'><th>순위</th><th>제목</th><th>출처</th></tr>"
            f"{rows}</table>"
        )

    if changes["removed"]:
        rows = ""
        for r in changes["removed"]:
            rows += (
                f"<tr>"
                f"<td><b>{r['rank']}</b></td>"
                f"<td>[{r['type']}] {r['title']}</td>"
                f"<td>{r.get('source','')}</td>"
                f"</tr>"
            )
        sections.append(
            f"<h3 style='color:#c62828'>❌ 순위 이탈 ({len(changes['removed'])}건)</h3>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
            f"<tr style='background:#ffebee'><th>이전순위</th><th>제목</th><th>출처</th></tr>"
            f"{rows}</table>"
        )

    # 현재 전체 순위 요약 (상위 15위)
    top_rows = ""
    for r in curr[:15]:
        top_rows += (
            f"<tr>"
            f"<td align='center'>{r['rank']}</td>"
            f"<td>[{r['type']}] <a href='{r['url']}'>{r['title']}</a></td>"
            f"<td>{r.get('source','')}</td>"
            f"</tr>"
        )
    sections.append(
        f"<h3 style='color:#37474f'>📋 현재 전체 순위 (상위 15위)</h3>"
        f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        f"<tr style='background:#eceff1'><th>순위</th><th>제목</th><th>출처</th></tr>"
        f"{top_rows}</table>"
    )

    body = "\n".join(sections)
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:900px;margin:auto;padding:20px">
  <h2 style="background:#1565c0;color:white;padding:12px 16px;border-radius:6px">
    네이버 '복재성' 검색 순위 변화 알림
  </h2>
  <p style="color:#555">체크 시각: <b>{ts}</b> &nbsp;|&nbsp; 총 {len(curr)}건 수집</p>
  {body}
  <hr>
  <p style="color:#999;font-size:12px">자동 발송 · 네이버 순위 체커</p>
</body>
</html>
"""


def send_email(subject: str, html_body: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")

    if not sender or not password:
        log.warning("EMAIL_SENDER / EMAIL_PASSWORD 환경변수 미설정 → 이메일 건너뜀")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, [NOTIFY_EMAIL], msg.as_string())
        log.info("이메일 발송 완료 → %s", NOTIFY_EMAIL)
    except Exception as e:
        log.error("이메일 발송 실패: %s", e)
        raise


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

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
    html = ""
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

    # 3단계: 블로그 검색 (보완용)
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

    final_results = integrated_results or blog_results

    if not final_results:
        log.warning("수집된 결과가 없습니다. HTML 구조 확인 필요.")
        debug_path = os.path.join(RESULTS_DIR, now.strftime("%Y-%m-%d_%H00") + "_debug.html")
        try:
            os.makedirs(RESULTS_DIR, exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html or "no html")
            log.info("디버그 HTML 저장: %s", debug_path)
        except Exception:
            pass
        return

    # 4단계: 이전 결과 로드 → 변화 감지
    prev_results = load_previous_results()

    # 5단계: 현재 결과 저장
    save_results(final_results, now)
    append_to_history(final_results, now)

    # 6단계: 변화 분석 및 이메일 발송
    if prev_results is None:
        log.info("이전 결과 없음 (첫 실행) → 이메일 건너뜀")
    else:
        changes = detect_changes(prev_results, final_results)
        if changes["has_changes"]:
            n_chg = len(changes["rank_changes"])
            n_new = len(changes["new"])
            n_del = len(changes["removed"])
            subject = (
                f"[복재성 순위변화] "
                f"{'순위변동 ' + str(n_chg) + '건 ' if n_chg else ''}"
                f"{'신규 ' + str(n_new) + '건 ' if n_new else ''}"
                f"{'이탈 ' + str(n_del) + '건' if n_del else ''}"
                f"| {now.strftime('%m/%d %H시')}"
            ).strip()
            html_body = build_email_html(changes, final_results, now)
            send_email(subject, html_body)
        else:
            log.info("순위 변화 없음 → 이메일 발송 안 함")

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
