#!/usr/bin/env python3
"""Multi-SSC Monitor - Direct Connection Mode"""

import os, re, json, time, logging, requests
from datetime import datetime, timedelta
from dateutil.parser import parse as dtparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

MAIN_SSC_API = "https://ssc.gov.in/api/public/noticeboard?page=0&size=50&sort=createdOn,desc"
MAIN_SSC_URL = "https://ssc.gov.in/home/notice-board"
SSC_NR_URL = "https://sscnr.nic.in/newlook/site/Whatsnew.html"
STATE_FILE = "/data/multi_ssc_state.json"
LOOKBACK_DAYS = 12
CHECK_INTERVAL = 300
DATE_RE_MAIN = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})")
DATE_RE_NR = re.compile(r"\[(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\]")

def send_telegram(msg: str) -> bool:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat): return False
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=10).raise_for_status()
        return True
    except Exception as e:
        logging.error("Telegram error → %s", e); return False

def _ensure_dir(): os.makedirs("/data", exist_ok=True)
def load_state():
    _ensure_dir()
    try: return json.load(open(STATE_FILE))
    except: return {"main": [], "nr": []}
def save_state(s): _ensure_dir(); json.dump(s, open(STATE_FILE,"w"), indent=2)

def new_driver():
    opts = Options()
    opts.binary_location = "/usr/bin/chromium"
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    return webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=opts)

def scrape_main_api():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://ssc.gov.in/"
    }
    r = requests.get(MAIN_SSC_API, timeout=15, headers=headers)
    r.raise_for_status()
    data = r.json()
    cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
    out = []
    for item in data.get("content", []):
        try:
            d = datetime.fromisoformat(item["createdOn"][:10]).date()
            if d < cutoff: break
            title = item["title"].strip()
            if not title: continue
            link = f"https://ssc.gov.in{item.get('fileUrl','')}" or None
            uid = f"main-{d}-{title[:80]}"
            out.append({"id":uid,"date":d,"title":title,"link":link,"src":"Main SSC"})
        except: continue
    return out

def scrape_main_html():
    out, drv = [], None
    try:
        drv = new_driver()
        drv.set_page_load_timeout(45)
        drv.execute_cdp_cmd("Network.setBlockedURLs", 
                            {"urls":["*.png","*.jpg","*.gif","*.svg","*.css","*.woff*"]})
        drv.execute_cdp_cmd("Network.enable", {})
        drv.get(MAIN_SSC_URL)
        WebDriverWait(drv, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.rightSection")))
        cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
        for row in drv.find_elements(By.CSS_SELECTOR, "div.flex"):
            try:
                left = row.find_element(By.CSS_SELECTOR, "div.leftSection").text
                m = DATE_RE_MAIN.search(" ".join(left.split()))
                if not m: continue
                d = dtparse(" ".join(m.groups())).date()
                if d < cutoff: continue
                title = row.find_element(By.CSS_SELECTOR, "div.rightSection p.text").text.strip()
                if not title: continue
                links = row.find_elements(By.CSS_SELECTOR, "div.rightSection a[href$='.pdf']")
                link = links[0].get_attribute("href") if links else None
                uid = f"main-{d}-{title[:80]}"
                out.append({"id":uid,"date":d,"title":title,"link":link,"src":"Main SSC"})
            except: continue
    finally:
        if drv: drv.quit()
    return out

def scrape_main():
    try: 
        notices = scrape_main_api()
        logging.info("✅ Main SSC API: %d notices", len(notices))
        return notices
    except Exception as e:
        logging.warning("API failed → %s. Trying HTML...", e)
        notices = scrape_main_html()
        logging.info("✅ Main SSC HTML: %d notices", len(notices))
        return notices

def scrape_nr():
    out, drv = [], None
    try:
        drv = new_driver()
        drv.set_page_load_timeout(45)
        drv.execute_cdp_cmd("Network.setBlockedURLs",
                            {"urls":["*.png","*.jpg","*.gif","*.svg","*.css","*.js","*.woff*"]})
        drv.execute_cdp_cmd("Network.enable", {})
        drv.get(SSC_NR_URL)
        html = drv.page_source
        cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
        for line in html.splitlines():
            m = DATE_RE_NR.search(line.strip())
            if not m: continue
            try:
                d = dtparse(" ".join(m.groups())).date()
                if d < cutoff: continue
                title = re.sub(r'\[.*?\]', '', re.sub(r'<[^>]+>', '', line)).strip()
                if len(title) < 10: continue
                uid = f"nr-{d}-{title[:80]}"
                out.append({"id":uid,"date":d,"title":title,"link":SSC_NR_URL,"src":"SSC NR"})
            except: continue
    finally:
        if drv: drv.quit()
    return out

def fmt(n):
    icon = "🏛️" if n["src"] == "Main SSC" else "🏢"
    msg = f"{icon} New {n['src']} Notice\n\n📅 {n['date']}\n📄 {n['title']}\n\n"
    if n["link"]: msg += "🔗 Open"
    return msg

def monitor():
    st = load_state()
    sent_main, sent_nr = set(st["main"]), set(st["nr"])
    main, nr = scrape_main(), scrape_nr()
    new_main = [n for n in main if n["id"] not in sent_main]
    new_nr = [n for n in nr if n["id"] not in sent_nr]
    logging.info("🆕 New notices → Main:%d | NR:%d", len(new_main), len(new_nr))
    for n in new_main + new_nr:
        if send_telegram(fmt(n)):
            (sent_main if n["src"] == "Main SSC" else sent_nr).add(n["id"])
            time.sleep(1)
    st["main"], st["nr"] = list(sent_main)[-500:], list(sent_nr)[-500:]
    save_state(st)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        raise SystemExit("❌ Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    
    # Check IP location first
    try:
        ip_info = requests.get("http://ipinfo.io/json", timeout=10).json()
        logging.info("🌍 Connecting from: %s (%s)", ip_info.get('country', 'Unknown'), ip_info.get('city', 'Unknown'))
    except:
        logging.info("🌍 IP location check failed")
    
    logging.info("🚀 SSC monitor started (Direct connection)")
    while True:
        try: monitor()
        except Exception as e: logging.error("💥 Cycle crashed → %s", e)
        time.sleep(CHECK_INTERVAL)
