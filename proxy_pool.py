"""
proxy_pool.py
──────────────────────────────────────────────────────────────
• Fetches free proxies from multiple public TXT feeds.
    – Three feeds country-filtered to IN.
    – Three global feeds as fallback when India list is empty.
• Filters out SOCKS entries automatically.
• Verifies HTTPS CONNECT via https://httpbin.org/ip.
• Provides get() / ban() helpers used by main.py.
"""

import requests, logging, random, time, threading

# ── TXT feeds (all return ip:port per line) ──────────────────
INDIA_TXT = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&country=IN&format=txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https&country=IN&format=txt",
    "https://pubproxy.com/api/proxy?limit=20&country=IN&format=txt",
]

GLOBAL_TXT = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/https.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies.txt",
]

_FETCH_TIMEOUT = 10     # s
_TEST_TIMEOUT  = 6      # s
_REFRESH_EVERY = 3_600  # s
_MAX_TEST      = 300    # test at most 300 per refresh
_MAX_GOOD      = 50     # keep first 50 that work
_TEST_URL      = "https://httpbin.org/ip"

_lock           = threading.Lock()
_good: list[str] = []
_bad:  set[str]  = set()
_last_refresh   = 0.0


def _grab(urls: list[str]) -> list[str]:
    found = set()
    for url in urls:
        try:
            r = requests.get(url, timeout=_FETCH_TIMEOUT)
            r.raise_for_status()
            for raw in r.text.splitlines():
                raw = raw.strip()
                if not raw or "socks" in raw.lower():
                    continue
                if "://" not in raw:
                    raw = f"http://{raw}"
                found.add(raw)
        except Exception as e:
            logging.warning("Proxy source error %s → %s", url, e)
    return list(found)


def _is_https_ok(proxy: str) -> bool:
    try:
        requests.get(_TEST_URL,
                     proxies={"http": proxy, "https": proxy},
                     timeout=_TEST_TIMEOUT)
        return True
    except Exception:
        return False


def _refresh():
    global _good, _bad, _last_refresh
    _last_refresh = time.time()
    _bad.clear()

    # 1️⃣ try India-only feeds
    cand = _grab(INDIA_TXT)
    if not cand:
        logging.warning("No Indian proxies found, using global feeds")
        cand = _grab(GLOBAL_TXT)
    else:
        cand.extend(_grab(GLOBAL_TXT))              # append globals for backup

    cand = cand[:_MAX_TEST]
    logging.info("Fetched %d proxy candidates", len(cand))

    good = []
    for p in cand:
        if _is_https_ok(p):
            good.append(p)
            if len(good) >= _MAX_GOOD:
                break
    _good = good
    logging.info("Verified %d working proxies", len(_good))


def _refresh_if_needed():
    if not _good or time.time() - _last_refresh > _REFRESH_EVERY:
        _refresh()


# ── public helpers ────────────────────────────────────────────
def get() -> str | None:
    with _lock:
        _refresh_if_needed()
        return random.choice(_good) if _good else None


def ban(proxy: str):
    with _lock:
        _bad.add(proxy)
        if proxy in _good:
            _good.remove(proxy)
            logging.info("Banned proxy %s (%d remaining)", proxy, len(_good))
