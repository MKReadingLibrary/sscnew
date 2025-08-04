"""
proxy_pool.py
──────────────────────────────────────────────────────────────
• Fetches fresh Indian HTTP/HTTPS proxies from public sources.
• Verifies each via https://httpbin.org/ip (HTTPS CONNECT test).
• Provides thread-safe get()/ban() helpers for the scraper.
"""

import requests, logging, random, time, threading

# Public JSON/TXT endpoints that return "ip:port" lists (no key required)
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies"
    "&protocol=http&country=IN&timeout=7000&format=txt",
    "https://api.proxyscrape.com/v2/?request=getproxies"
    "&protocol=https&country=IN&timeout=7000&format=txt",
]

_FETCH_TIMEOUT  = 10          # s
_TEST_TIMEOUT   = 6           # s
_REFRESH_EVERY  = 3_600       # s  (1 h)
_MAX_GOOD       = 20          # keep first N working proxies
_TEST_URL       = "https://httpbin.org/ip"

_lock          = threading.Lock()
_good: list[str] = []         # verified live proxies
_bad:  set[str]  = set()      # banned this run
_last_refresh   = 0.0


# ── internal helpers ───────────────────────────────────────────
def _grab_candidates() -> list[str]:
    """Download raw proxy lines from all sources."""
    found = set()
    for url in PROXY_SOURCES:
        try:
            r = requests.get(url, timeout=_FETCH_TIMEOUT)
            r.raise_for_status()
            for line in r.text.splitlines():
                ip = line.strip()
                if ip:
                    if "://" not in ip:
                        ip = f"http://{ip}"
                    found.add(ip)
        except Exception as e:
            logging.warning("Proxy source failed %s → %s", url, e)
    return list(found)


def _is_https_working(proxy: str) -> bool:
    try:
        requests.get(_TEST_URL,
                     proxies={"http": proxy, "https": proxy},
                     timeout=_TEST_TIMEOUT)
        return True
    except Exception:
        return False


def _refresh_if_needed():
    global _last_refresh, _good, _bad
    now = time.time()
    if _good and now - _last_refresh < _REFRESH_EVERY:
        return                          # still fresh
    _last_refresh = now
    _bad.clear()

    candidates = _grab_candidates()
    logging.info("Fetched %d proxy candidates", len(candidates))

    good: list[str] = []
    for p in candidates:
        if _is_https_working(p):
            good.append(p)
            if len(good) >= _MAX_GOOD:
                break
    _good = good
    logging.info("Verified %d working proxies", len(_good))


# ── public API ─────────────────────────────────────────────────
def get() -> str | None:
    """Return a random live proxy or None if none available."""
    with _lock:
        _refresh_if_needed()
        return random.choice(_good) if _good else None


def ban(proxy: str):
    """Mark a proxy as dead so it is not returned again this run."""
    with _lock:
        _bad.add(proxy)
        if proxy in _good:
            _good.remove(proxy)
            logging.info("Proxy banned %s (%d left)", proxy, len(_good))
