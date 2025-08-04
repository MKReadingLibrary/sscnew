#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-SSC Monitor (API + HTML fallback + Selenium with proxy, Telegram direct)
"""

import os, re, json, time, logging, random, requests
from datetime import datetime, timedelta
from dateutil.parser import parse as dtparse

# ───── selenium & proxy ─────
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ───────── CONFIG ─────────
MAIN_SSC_API = "https://ssc.gov.in/api/public/noticeboard?page=0&size=50&sort=createdOn,desc"
MAIN_SSC_URL = "https://ssc.gov.in/home/notice-board"
SSC_NR_URL   = "https://sscnr.nic.in/newlook/site/Whatsnew.html"

STATE_FILE   = "/data/multi_ssc_state.json"
LOOKBACK_DAYS = 12
CHECK_INTERVAL = 300

DATE_RE_MAIN = re.compile(r'([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})')
DATE_RE_NR   = re.compile(r'\[(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\]')

# ───────── PROXIES ─────────
PROXY_LIST = [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()]

def pick_proxy():
    return random.choice(PROXY_LIST) if PROXY_LIST else None

def swire_opts():
    proxy = pick_proxy()
    if not proxy:
        return None
    return {
        "proxy": {
            "http":  proxy,
            "https": proxy,
            "no_proxy": "localhost,127.0.0.1"
        }
    }

def req_proxies():
    proxy = pick_proxy()
    return {"http": proxy, "https": proxy} if proxy else None

# ───────── TELEGRAM (DIRECT) ───────
def send_telegram(msg: str) -> bool:
    """
    Send message directly (no proxies) to avoid failures on api.telegram.org.
    """
    tok  = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False

    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = {
        "chat_id": chat,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        requests.post(url, data=data, timeout=10).raise_for_status()
        return True
    except Exception as e:
        logging.error("Telegram error → %s", e)
        return False

# ───────── STATE ─────────
def _ensure_dir():
    os.makedirs("/data", exist_ok=True)

def load_state():
    _ensure_dir()
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"main": [], "nr": []}

def save_state(s):
    _ensure_dir()
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)

# ───────── SELENIUM HELPER ──────
def new_driver(use_proxy: bool):
    opts = Options()
    opts.binary_location = "/usr/bin/chromium"
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")

    sw_opts = swire_opts() if use_proxy else None
    if sw_opts:
        logging.info("🔗 Using proxy %s", sw_opts["proxy"]["http"])

    return webdriver.Chrome(service=Service("/usr/bin/chromedriver"),
                            options=opts,
                            seleniumwire_options=sw_opts)

# ───────── MAIN SSC SCRAPERS ──────
def scrape_main_api():
    out = []
    try:
        resp = requests.get(MAIN_SSC_API, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"},
                            proxies=req_proxies())
        resp.raise_for_status()
        data = resp.json()

        cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
        for item in data.get("content", []):
            try:
                date_str = item.get("createdOn", "")[:10]
                notice_date = datetime.fromisoformat(date_str).date()
                if notice_date < cutoff:
                    break
                title = item.get("title", "").strip()
                if not title:
                    continue
                file_url = item.get("fileUrl", "")
                link = f"https://ssc.gov.in{file_url}" if file_url else None
                uid = f"main-{notice_date}-{title[:80]}"
                out.append({"id": uid, "date": notice_date,
                            "title": title, "link": link, "src": "Main SSC"})
            except Exception:
                continue
        logging.info("✅ Main SSC API successful")
        return out
    except Exception as e:
        logging.warning("Main SSC API failed → %s", e)
        return None

def scrape_main_html():
    out, drv = [], None
    try:
        logging.info("🔄 HTML fallback for Main SSC…")
        drv = new_driver(use_proxy=True)
        drv.set_page_load_timeout(45)
        drv.execute_cdp_cmd("Network.setBlockedURLs",
                            {"urls": ["*.png","*.jpg","*.gif","*.svg","*.css","*.woff*"]})
        drv.execute_cdp_cmd("Network.enable", {})
        drv.get(MAIN_SSC_URL)

        WebDriverWait(drv, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.rightSection"))
        )

        cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
        for row in drv.find_elements(By.CSS_SELECTOR, "div.flex"):
            try:
                left = row.find_element(By.CSS_SELECTOR, "div.leftSection").text
                m = DATE_RE_MAIN.search(" ".join(left.split()))
                if not m:
                    continue
                notice_date = dtparse(" ".join(m.groups())).date()
                if notice_date < cutoff:
                    continue
                title = row.find_element(
                    By.CSS_SELECTOR, "div.rightSection p.text").text.strip()
                if not title:
                    continue
                link_elem = row.find_elements(
                    By.CSS_SELECTOR, "div.rightSection a[href$='.pdf']")
                link = link_elem[0].get_attribute("href") if link_elem else None
                uid = f"main-{notice_date}-{title[:80]}"
                out.append({"id": uid, "date": notice_date,
                            "title": title, "link": link, "src": "Main SSC"})
            except Exception:
                continue
        logging.info("✅ Main SSC HTML fallback successful")
    except Exception as e:
        logging.error("Main SSC HTML fallback failed → %s", e)
    finally:
        if drv:
            drv.quit()
    return out

def scrape_main():
    res = scrape_main_api()
    return res if res is not None else scrape_main_html()

# ───────── SSC NR SCRAPER ──────
def scrape_nr():
    out, drv = [], None
    try:
        drv = new_driver(use_proxy=False)
        drv.set_page_load_timeout(45)
        drv.execute_cdp_cmd("Network.setBlockedURLs",
                            {"urls": ["*.png","*.jpg","*.gif","*.svg",
                                      "*.css","*.js","*.woff*"]})
        drv.execute_cdp_cmd("Network.enable", {})
        drv.get(SSC_NR_URL)
        html = drv.page_source

        cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
        for line in html.splitlines():
            line = line.strip()
            if not line:
                continue
            m = DATE_RE_NR.search(line)
            if not m:
                continue
            try:
                notice_date = dtparse(" ".join(m.groups())).date()
                if notice_date < cutoff:
                    continue
                title = re.sub(r'\[.*?\]', '', re.sub(r'<[^>]+>', '', line)).strip()
                if len(title) < 10:
                    continue
                uid = f"nr-{notice_date}-{title[:80]}"
                out.append({"id": uid, "date": notice_date,
                            "title": title, "link": SSC_NR_URL, "src": "SSC NR"})
            except Exception:
                continue
    except Exception as e:
        logging.error("SSC NR scraper error → %s", e)
    finally:
        if drv:
            drv.quit()
    return out

# ───────── UTIL ──────
def format_msg(n):
    icon = "🏛️" if n["src"] == "Main SSC" else "🏢"
    msg = (f"{icon} New {n['src']} Notice\n\n"
           f"📅 {n['date']}\n"
           f"📄 {n['title']}\n\n")
    if n["link"]:
        msg += "🔗 Open"
    return msg

# ───────── MAIN CYCLE ──────
def monitor_cycle():
    state = load_state()
    sent_main = set(state.get("main", []))
    sent_nr   = set(state.get("nr", []))

    main_notices = scrape_main() or []
    nr_notices   = scrape_nr()   or []

    main_new = [n for n in main_notices if n["id"] not in sent_main]
    nr_new   = [n for n in nr_notices   if n["id"] not in sent_nr]

    logging.info("Main SSC: %d total | %d new", len(main_notices), len(main_new))
    logging.info("SSC NR : %d total | %d new", len(nr_notices), len(nr_new))

    for notice in main_new + nr_new:
        if send_telegram(format_msg(notice)):
            (sent_main if notice["src"] == "Main SSC" else sent_nr).add(notice["id"])
            time.sleep(1)

    state["main"] = list(sent_main)[-500:]
    state["nr"]   = list(sent_nr)[-500:]
    save_state(state)

# ───────── MAIN LOOP ──────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    if PROXY_LIST:
        logging.info("Proxies loaded: %d", len(PROXY_LIST))
    else:
        logging.warning("⚠️  No proxies configured (PROXY_LIST env var empty)")

    logging.info("Multi-SSC monitor started")
    while True:
        try:
            monitor_cycle()
        except Exception as e:
            logging.error("Monitor cycle crashed → %s", e)
        time.sleep(CHECK_INTERVAL)
