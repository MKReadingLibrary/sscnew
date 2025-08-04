"""
proxy_pool.py  —  Spys.one-only mode
──────────────────────────────────────────────────────────────
1.  Downloads the HTML table from https://spys.one/free-proxy-list/IN/
2.  Extracts every IP + port that appears in the first column.
3.  Verifies HTTPS CONNECT against https://httpbin.org/ip.
"""

import re, time, random, threading, logging, requests

SPYS_URL       = "https://spys.one/free-proxy-list/IN/"
_FETCH_TIMEOUT = 15    # s
_TEST_TIMEOUT  = 8     # s
_REFRESH_EVERY = 3_600 # s
_MAX_GOOD      = 50    # first 50 HTTPS-working proxies we meet
_TEST_URL      = "https://httpbin.org/ip"

_lock           = threading.Lock()
_good: list[str] = []
_last_refresh   = 0.0


def _scrape_spys() -> list[str]:
    """Return a list of ip:port strings scraped from Spys.one."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/117.0 Safari/537.36",
        "Referer": "https://spys.one/",
        "Accept-Language": "en-US,en;q=0.9"
    }
    logging.info("🔗 Fetching Spys.one proxy table …")
    html = requests.get(SPYS_URL, headers=headers,
                        timeout=_FETCH_TIMEOUT).text

    # The first table cell of each row contains IP + port separated by a colon
    # Example HTML chunk: 47.247.141.78:8080</font></td>
    proxies = re.findall(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})", html)
    scraped = [f"http://{ip}:{port}" for ip, port in proxies]
    logging.info("🗒️  Scraped %d proxies from Spys.one", len(scraped))
    return scraped


def _is_https_ok(proxy: str) -> bool:
    try:
        r = requests.get(_TEST_URL,
                         proxies={"http": proxy, "https": proxy},
                         timeout=_TEST_TIMEOUT)
        return r.status_code == 200 and "origin" in r.text
    except Exception:
        return False


def _refresh():
    global _good, _last_refresh
    _last_refresh = time.time()
    candidates = _scrape_spys()

    good = []
    for p in candidates:
        if _is_https_ok(p):
            good.append(p)
            logging.info("✅ %s works", p)
            if len(good) >= _MAX_GOOD:
                break

    _good = good
    logging.info("🎉 %d working HTTPS proxies ready", len(_good))


def _ensure_fresh():
    if not _good or (time.time() - _last_refresh > _REFRESH_EVERY):
        _refresh()


# ── public helpers — used by main.py ──────────────────────────
def get() -> str | None:
    with _lock:
        _ensure_fresh()
        return random.choice(_good) if _good else None


def ban(proxy: str):
    with _lock:
        if proxy in _good:
            _good.remove(proxy)
            logging.info("🚫 Proxy banned: %s (%d remaining)", proxy, len(_good))
