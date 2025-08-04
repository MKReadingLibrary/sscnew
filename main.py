#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-SSC Monitor (API + HTML fallback + Selenium with Proxy)
"""

import os, re, json, time, logging, requests, shutil, random
from datetime import datetime, timedelta
from dateutil.parser import parse as dtparse
from seleniumwire import webdriver  # Changed to selenium-wire
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ───────── CONFIG ─────────
MAIN_SSC_API = "https://ssc.gov.in/api/public/noticeboard?page=0&size=50&sort=createdOn,desc"
MAIN_SSC_URL = "https://ssc.gov.in/home/notice-board"
SSC_NR_URL = "https://sscnr.nic.in/newlook/site/Whatsnew.html"
STATE_FILE = "/data/multi_ssc_state.json"
LOOKBACK_DAYS = 12
CHECK_INTERVAL = 300
DATE_RE_MAIN = re.compile(r'([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})')
DATE_RE_NR = re.compile(r'\[(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\]')

# ───────── PROXY CONFIG ─────────
PROXY_LIST = [
    # Add your proxy servers here. Examples:
    # "http://username:password@proxy1.example.com:8080",
    # "http://username:password@proxy2.example.com:8080",
    # "http://proxy3.example.com:3128",  # No auth proxy
]

def get_random_proxy():
    """Get a random proxy from the list"""
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)

def get_proxy_config():
    """Get proxy configuration for selenium-wire"""
    proxy = get_random_proxy()
    if not proxy:
        return None
    
    return {
        'proxy': {
            'http': proxy,
            'https': proxy,
            'no_proxy': 'localhost,127.0.0.1'
        }
    }

def get_requests_proxy():
    """Get proxy configuration for requests"""
    proxy = get_random_proxy()
    if not proxy:
        return None
    
    return {
        'http': proxy,
        'https': proxy
    }

# ───────── TELEGRAM ─────────
def send_telegram(msg: str) -> bool:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat): return False
    
    try:
        # Use proxy for Telegram if available
        proxies = get_requests_proxy()
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                     data={"chat_id": chat, "text": msg,
                           "parse_mode": "HTML",
                           "disable_web_page_preview": True},
                     timeout=10, proxies=proxies).raise_for_status()
        return True
    except Exception as e:
        logging.error("Telegram error → %s", e)
        return False

# ───────── STATE ─────────
def ensure_data_dir():
    if not os.path.exists("/data"):
        os.makedirs("/data", exist_ok=True)

def load_state():
    ensure_data_dir()
    if os.path.isfile(STATE_FILE):
        try: return json.load(open(STATE_FILE))
        except: pass
    return {"main": [], "nr": []}

def save_state(s):
    ensure_data_dir()
    json.dump(s, open(STATE_FILE, "w"), indent=2)

# ───────── SELENIUM HELPER ──────
def create_driver(use_proxy=True):
    opts = Options()
    opts.binary_location = "/usr/bin/chromium"
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    
    # Get proxy configuration
    proxy_config = get_proxy_config() if use_proxy else None
    
    if proxy_config:
        logging.info("🔄 Using proxy for Selenium")
        return webdriver.Chrome(service=Service("/usr/bin/chromedriver"), 
                              options=opts, 
                              seleniumwire_options=proxy_config)
    else:
        logging.info("🔄 No proxy configured for Selenium")
        return webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=opts)

# ───────── MAIN SSC SCRAPERS ──────
def scrape_main_api():
    """Try SSC JSON API first (faster) with proxy support"""
    out = []
    try:
        # Use proxy for requests
        proxies = get_requests_proxy()
        if proxies:
            logging.info("🔄 Using proxy for API request")
        
        resp = requests.get(MAIN_SSC_API, timeout=10, 
                          headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                          proxies=proxies)
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
                
                out.append({
                    "id": uid,
                    "date": notice_date,
                    "title": title,
                    "link": link,
                    "src": "Main SSC"
                })
            except Exception:
                continue
        
        logging.info("✅ Main SSC API successful")
        return out
        
    except Exception as e:
        logging.warning("Main SSC API failed → %s", e)
        return None  # Signal to try HTML fallback

def scrape_main_html():
    """Fallback to HTML scraping if API fails with proxy support"""
    out, drv = [], None
    try:
        logging.info("🔄 Trying Main SSC HTML fallback...")
        drv = create_driver(use_proxy=True)  # Use proxy for geoblocked site
        drv.set_page_load_timeout(45)
        
        # Allow JS but block heavy resources
        drv.execute_cdp_cmd("Network.setBlockedURLs", {
            "urls": ["*.png","*.jpg","*.jpeg","*.gif","*.svg","*.css","*.woff*"]
        })
        drv.execute_cdp_cmd("Network.enable", {})
        
        drv.get(MAIN_SSC_URL)
        WebDriverWait(drv, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.rightSection"))
        )
        
        cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
        
        for row in drv.find_elements(By.CSS_SELECTOR, "div.flex"):
            try:
                left_text = row.find_element(By.CSS_SELECTOR, "div.leftSection").text
                m = DATE_RE_MAIN.search(" ".join(left_text.split()))
                if not m:
                    continue
                
                notice_date = dtparse(" ".join(m.groups())).date()
                if notice_date < cutoff:
                    continue
                
                title = row.find_element(By.CSS_SELECTOR, "div.rightSection p.text").text.strip()
                if not title:
                    continue
                
                link_elem = row.find_elements(By.CSS_SELECTOR, "div.rightSection a[href$='.pdf']")
                link = link_elem[0].get_attribute("href") if link_elem else None
                uid = f"main-{notice_date}-{title[:80]}"
                
                out.append({
                    "id": uid,
                    "date": notice_date,
                    "title": title,
                    "link": link,
                    "src": "Main SSC"
                })
            except Exception:
                continue
        
        logging.info("✅ Main SSC HTML fallback successful")
        return out
        
    except Exception as e:
        logging.error("❌ Main SSC HTML fallback also failed → %s", e)
        return []
    finally:
        if drv:
            drv.quit()

def scrape_main():
    """Try API first, fall back to HTML if needed"""
    # Try API first
    result = scrape_main_api()
    if result is not None:
        return result
    
    # API failed, try HTML with proxy
    return scrape_main_html()

# ───────── SSC NR SCRAPER ──────
def scrape_nr():
    """Scrape SSC NR with Selenium (no proxy needed as it works)"""
    out, drv = [], None
    try:
        drv = create_driver(use_proxy=False)  # No proxy needed for NR
        drv.set_page_load_timeout(45)
        
        # Block all heavy resources for static content
        drv.execute_cdp_cmd("Network.setBlockedURLs", {
            "urls": ["*.png","*.jpg","*.jpeg","*.gif","*.svg","*.css","*.js","*.woff*"]
        })
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
                
                out.append({
                    "id": uid,
                    "date": notice_date,
                    "title": title,
                    "link": SSC_NR_URL,
                    "src": "SSC NR"
                })
            except Exception:
                continue
                
    except Exception as e:
        logging.error("SSC NR scraper error → %s", e)
    finally:
        if drv:
            drv.quit()
    
    return out

# ───────── FORMATTING ─────────
def format_msg(n):
    icon = "🏛️" if n["src"] == "Main SSC" else "🏢"
    msg = (f"{icon} New {n['src']} Notice\n\n"
           f"📅 {n['date']}\n"
           f"📄 {n['title']}\n\n")
    if n["link"]:
        msg += f"🔗 Open"
    return msg

# ───────── MAIN CYCLE ─────────
def monitor_cycle():
    state = load_state()
    sent_main = set(state.get("main", []))
    sent_nr = set(state.get("nr", []))
    
    # Scrape both sources
    try:
        main_notices = scrape_main()
    except Exception as e:
        logging.error("Main scraper completely failed → %s", e)
        main_notices = []
    
    try:
        nr_notices = scrape_nr()
    except Exception as e:
        logging.error("NR scraper failed → %s", e)
        nr_notices = []
    
    # Find new notices
    main_new = [n for n in main_notices if n["id"] not in sent_main]
    nr_new = [n for n in nr_notices if n["id"] not in sent_nr]
    
    logging.info("Main SSC: %d total | %d new", len(main_notices), len(main_new))
    logging.info("SSC NR: %d total | %d new", len(nr_notices), len(nr_new))
    
    # Send notifications
    for notice in main_new + nr_new:
        if send_telegram(format_msg(notice)):
            if notice["src"] == "Main SSC":
                sent_main.add(notice["id"])
            else:
                sent_nr.add(notice["id"])
            time.sleep(1)
    
    # Save updated state
    state["main"] = list(sent_main)[-500:]
    state["nr"] = list(sent_nr)[-500:]
    save_state(state)

# ───────── MAIN LOOP ─────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    
    if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    
    if not PROXY_LIST:
        logging.warning("⚠️ No proxies configured - may face geoblocking")
    else:
        logging.info(f"✅ Configured with {len(PROXY_LIST)} proxies")
    
    logging.info("Multi-SSC monitor started (API + HTML fallback + Proxy)")
    
    while True:
        try:
            monitor_cycle()
        except Exception as e:
            logging.error("Monitor cycle crashed → %s", e)
        time.sleep(CHECK_INTERVAL)
