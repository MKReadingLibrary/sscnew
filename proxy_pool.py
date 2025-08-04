"""
proxy_pool.py
──────────────────────────────────────────────────────────────
• Grabs Indian HTTP/HTTPS proxies from public APIs.
• Skips SOCKS proxies and verifies HTTPS CONNECT via httpbin.
• Exposes get() / ban() helpers for main.py.
"""

import requests, logging, random, time, threading

# Public endpoints returning plain ip:port lists
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies"
    "&protocol=http&country=IN&timeout=7000&format=txt",
    "https://api.proxyscrape.com/v2/?request=getproxies"
    "&protocol=https&country=IN&timeout=7000&format=txt",
]

_FETCH_TIMEOUT  = 10    # s
_TEST_TIMEOUT   = 6     # s
_REFRESH_EVERY  = 3_600 # s
_MAX_GOOD       = 30    # keep ≤30 verified proxies
_MAX_TEST       = 120   # test at most 120 per refresh
_TEST_URL       = "https://httpbin.org/ip"

_lock           = threading.Lock()
_good: list[str] = []
_bad:  set[str]  = set()
_last_refresh   = 0.0


# ── internal helpers ───────────────────────────────────────────
def _grab_candidates() -> list[str]:
    found = set()
    for url in PROXY_SOURCES:
        try:
            r = requests.get(url, timeout=_FETCH_TIMEOUT)
            r.raise_for_status()
            for line in r.text.splitlines():
                raw = line.strip()
                if not raw or "socks" in raw.lower():       # ← skip SOCKS
                    continue
                if "://" not in raw:
                    raw = f"http://{raw}"
                found.add(raw)
        except Exception as e:
            logging.warning("Proxy source error %s → %s", url, e)
    return list(found)[:_MAX_TEST]


def _is_https_working(proxy: str) -> bool:
    try:
        requests.get(_TEST_URL,
                     proxies={"http": proxy, "https": proxy},
                     timeout=_TEST_TIMEOUT)
        return True
    except Exception:
        return False


def _refresh_if_needed():
    global _good, _bad, _last_refresh
    now = time.time()
    if _good and (now - _last_refresh < _REFRESH_EVERY):
        return
    _last_refresh = now
    _bad.clear()

    cand = _grab_candidates()
    logging.info("Fetched %d proxy candidates", len(cand))

    good = []
    for p in cand:
        if _is_https_working(p):
            good.append(p)
            if len(good) >= _MAX_GOOD:
                break
    _good = good
    logging.info("Verified %d working proxies", len(_good))


# ── public API ─────────────────────────────────────────────────
def get() -> str | None:
    with _lock:
        _refresh_if_needed()
        return random.choice(_good) if _good else None


def ban(proxy: str):
    with _lock:
        _bad.add(proxy)
        if proxy in _good:
            _good.remove(proxy)
            logging.info("Banned proxy %s (%d left)", proxy, len(_good))
