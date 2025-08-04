"""
proxy_pool.py  –  Light Indian proxy rotator
"""

import re, time, random, threading, logging, requests

SPYS_URL        = "https://spys.one/free-proxy-list/IN/"
_FETCH_TIMEOUT  = 12      # s
_TEST_TIMEOUT   = 6       # s
_REFRESH_EVERY  = 3_600   # s
_MAX_GOOD       = 40
_TEST_URL       = "https://httpbin.org/ip"

_lock, _good, _bad, _last = threading.Lock(), [], set(), 0.0
IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")

def _scrape_spys() -> list[str]:
    hdrs = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://spys.one/"
    }
    logging.info("Fetching Indian proxy table …")
    html = requests.get(SPYS_URL, timeout=_FETCH_TIMEOUT, headers=hdrs).text
    return [f"http://{ip}:{port}" for ip, port in IP_RE.findall(html)]

def _is_https_ok(proxy: str) -> bool:
    try:
        requests.get(_TEST_URL,
                     proxies={"http": proxy, "https": proxy},
                     timeout=_TEST_TIMEOUT)
        return True
    except Exception:
        return False

def _refresh():
    global _good, _bad, _last
    _last, _bad = time.time(), set()
    cand = _scrape_spys()
    logging.info("Scraped %d candidates", len(cand))
    good = []
    for p in cand:
        if _is_https_ok(p):
            good.append(p)
            logging.info("Proxy OK: %s", p)
            if len(good) >= _MAX_GOOD:
                break
    _good = good
    logging.info("Ready proxies: %d", len(_good))

def _ensure():
    if not _good or time.time() - _last > _REFRESH_EVERY:
        _refresh()

# ── public helpers ───────────────────────────────────────────
def get() -> str | None:
    with _lock:
        _ensure()
        return random.choice(_good) if _good else None

def ban(proxy: str):
    with _lock:
        if proxy in _good:
            _good.remove(proxy)
            logging.info("Banned proxy %s (%d left)", proxy, len(_good))
