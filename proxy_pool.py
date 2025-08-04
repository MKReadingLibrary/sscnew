"""
proxy_pool.py
──────────────────────────────────────────────────────────────
• Fetches free proxies from reliable public TXT feeds.
• Filters out SOCKS entries automatically.
• Verifies HTTPS CONNECT via https://httpbin.org/ip.
• Uses multiple fallback sources when primary sources fail.
"""

import requests, logging, random, time, threading

# ── Reliable TXT sources (verified working as of 2025) ────────
PROXY_SOURCES = [
    # ProxyScrape API (most reliable)
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&country=IN&timeout=7000&format=txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https&country=IN&timeout=7000&format=txt",
    
    # Global fallbacks when India-specific fails
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=7000&format=txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https&timeout=7000&format=txt",
    
    # Alternative sources
    "https://proxyelite.info/http_proxies.txt",
    "https://spys.me/proxy.txt",
]

_FETCH_TIMEOUT = 15     # increased timeout
_TEST_TIMEOUT  = 8      # increased timeout  
_REFRESH_EVERY = 3_600  # s
_MAX_TEST      = 500    # test more candidates
_MAX_GOOD      = 50     # keep first 50 that work
_TEST_URL      = "https://httpbin.org/ip"

_lock           = threading.Lock()
_good: list[str] = []
_bad:  set[str]  = set()
_last_refresh   = 0.0


def _grab(urls: list[str]) -> list[str]:
    found = set()
    working_sources = 0
    
    for url in urls:
        try:
            logging.info("Fetching proxies from %s", url)
            r = requests.get(url, timeout=_FETCH_TIMEOUT)
            r.raise_for_status()
            
            lines = r.text.splitlines()
            source_count = 0
            
            for raw in lines:
                raw = raw.strip()
                if not raw or "socks" in raw.lower():
                    continue
                if "://" not in raw:
                    raw = f"http://{raw}"
                found.add(raw)
                source_count += 1
            
            if source_count > 0:
                working_sources += 1
                logging.info("✅ Got %d proxies from %s", source_count, url.split('/')[2])
            
        except Exception as e:
            logging.warning("❌ Proxy source failed %s → %s", url.split('/')[2] if '/' in url else url, e)
    
    logging.info("📊 %d sources worked, %d total proxies found", working_sources, len(found))
    return list(found)


def _is_https_ok(proxy: str) -> bool:
    try:
        resp = requests.get(_TEST_URL,
                           proxies={"http": proxy, "https": proxy},
                           timeout=_TEST_TIMEOUT)
        # Verify we got a proper response
        return resp.status_code == 200 and "origin" in resp.text
    except Exception:
        return False


def _refresh():
    global _good, _bad, _last_refresh
    _last_refresh = time.time()
    _bad.clear()

    cand = _grab(PROXY_SOURCES)
    cand = cand[:_MAX_TEST]
    logging.info("🔍 Testing %d proxy candidates for HTTPS support", len(cand))

    good = []
    tested = 0
    for p in cand:
        if _is_https_ok(p):
            good.append(p)
            logging.info("✅ Working proxy found: %s", p.split('//')[1] if '//' in p else p)
            if len(good) >= _MAX_GOOD:
                break
        tested += 1
        if tested % 50 == 0:
            logging.info("⏳ Tested %d/%d proxies, found %d working", tested, len(cand), len(good))
    
    _good = good
    logging.info("🎉 Final result: %d working HTTPS proxies ready", len(_good))


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
            logging.info("🚫 Banned proxy %s (%d remaining)", proxy, len(_good))
