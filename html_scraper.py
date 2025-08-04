
"""
html_scraper.py
──────────────────────────────────────────────────────────────
Downloads the SSC notice-board HTML through a rotating Indian
proxy, then extracts all fresh notices with BeautifulSoup.
"""

import re, logging, requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dateutil.parser import parse as dtparse
from proxy_pool import get as pick_proxy, ban as ban_proxy

MAIN_SSC_URL  = "https://ssc.gov.in/home/notice-board"
LOOKBACK_DAYS = 12

DATE_RE   = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})")
HEADERS   = {"User-Agent": "Mozilla/5.0"}

# ── internal helpers ─────────────────────────────────────────
def _fetch_html(max_tries: int = 8) -> str | None:
    """Return raw HTML, trying up to `max_tries` proxies."""
    for _ in range(max_tries):
        proxy = pick_proxy()
        if not proxy:
            break
        try:
            resp = requests.get(MAIN_SSC_URL, headers=HEADERS, timeout=15,
                                proxies={"http": proxy, "https": proxy})
            resp.raise_for_status()
            logging.info("HTML loaded via %s", proxy)
            return resp.text
        except Exception:
            ban_proxy(proxy)
    return None


def _parse_html(html: str) -> list[dict]:
    """Extract notice rows from the HTML string."""
    soup   = BeautifulSoup(html, "lxml")
    cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
    notices = []

    for flex in soup.select("div.flex"):
        left  = flex.select_one("div.leftSection")
        title_tag = flex.select_one("div.rightSection p.text")
        if not (left and title_tag):
            continue

        m = DATE_RE.search(left.get_text(" "))
        if not m:
            continue
        date = dtparse(" ".join(m.groups())).date()
        if date < cutoff:
            continue

        title = title_tag.get_text(strip=True)
        if not title:
            continue

        link_tag = flex.select_one("div.rightSection a[href$='.pdf']")
        link = link_tag["href"] if link_tag else None
        uid  = f"main-{date}-{title[:80]}"

        notices.append({
            "id":    uid,
            "date":  date,
            "title": title,
            "link":  link,
            "src":   "Main SSC"
        })
    return notices


# ── public API (what main.py calls) ──────────────────────────
def scrape_main_html() -> list[dict]:
    """Return list of notices using proxy-based HTML scraping."""
    html = _fetch_html()
    if not html:
        logging.error("All proxies failed for HTML fetch")
        return []
    return _parse_html(html)
