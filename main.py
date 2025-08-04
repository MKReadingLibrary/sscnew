#!/usr/bin/env python3
"""
Multi-SSC Monitor – fast proxy/HTML version
"""

import os, re, json, time, logging, requests
from datetime import datetime, timedelta
from dateutil.parser import parse as dtparse
from html_scraper import scrape_main_html

MAIN_SSC_API = "https://ssc.gov.in/api/public/noticeboard?page=0&size=50&sort=createdOn,desc"
SSC_NR_URL   = "https://sscnr.nic.in/newlook/site/Whatsnew.html"
DATE_RE_NR   = re.compile(r"\[(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\]")
STATE_FILE   = "/data/multi_ssc_state.json"
LOOKBACK_DAYS = 12
CHECK_INTERVAL = 300  # s

# ── helpers ──────────────────────────────────────────────────
def _ensure_dir(): os.makedirs("/data", exist_ok=True)
def load_state():
    _ensure_dir()
    try: return json.load(open(STATE_FILE))
    except: return {"main": [], "nr": []}
def save_state(s): _ensure_dir(); json.dump(s, open(STATE_FILE,"w"), indent=2)

def send_tg(msg: str) -> bool:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat): return False
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": msg,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=10)
        return True
    except Exception as e:
        logging.error("TG error → %s", e); return False

def fmt(n):
    icon = "🏛️" if n["src"] == "Main SSC" else "🏢"
    msg = f"{icon} New {n['src']} Notice\n\n📅 {n['date']}\n📄 {n['title']}\n\n"
    if n["link"]: msg += "🔗 Open"
    return msg

# ── MAIN SSC API ─────────────────────────────────────────────
def scrape_main_api():
    r = requests.get(MAIN_SSC_API, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()
    cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
    out=[]
    for item in data.get("content", []):
        try:
            d = datetime.fromisoformat(item["createdOn"][:10]).date()
            if d<cutoff: break
            title=item["title"].strip()
            if not title: continue
            link=f"https://ssc.gov.in{item.get('fileUrl','')}" or None
            uid=f"main-{d}-{title[:80]}"
            out.append({"id":uid,"date":d,"title":title,"link":link,"src":"Main SSC"})
        except: continue
    return out

def scrape_main():
    try: return scrape_main_api()
    except Exception as e:
        logging.warning("API failed → %s – falling back to HTML", e)
        return scrape_main_html()

# ── SSC NR (no proxy needed) ─────────────────────────────────
def scrape_nr():
    html = requests.get(SSC_NR_URL, timeout=20).text
    cutoff = datetime.utcnow().date() - timedelta(days=LOOKBACK_DAYS)
    out = []
    for line in html.splitlines():
        m = DATE_RE_NR.search(line)
        if not m: continue
        try:
            d = dtparse(" ".join(m.groups())).date()
            if d < cutoff: continue
            title = re.sub(r'\[.*?\]', '', re.sub(r'<[^>]+>', '', line)).strip()
            if len(title) < 10: continue
            uid = f"nr-{d}-{title[:80]}"
            out.append({"id": uid, "date": d, "title": title,
                        "link": SSC_NR_URL, "src": "SSC NR"})
        except: continue
    return out

# ── main loop ────────────────────────────────────────────────
def cycle():
    st = load_state()
    sent_main, sent_nr = set(st["main"]), set(st["nr"])
    main, nr = scrape_main(), scrape_nr()
    new_main = [n for n in main if n["id"] not in sent_main]
    new_nr   = [n for n in nr   if n["id"] not in sent_nr]
    logging.info("New notices → Main:%d | NR:%d", len(new_main), len(new_nr))
    for n in new_main + new_nr:
        if send_tg(fmt(n)):
            (sent_main if n["src"]=="Main SSC" else sent_nr).add(n["id"])
            time.sleep(1)
    st["main"], st["nr"] = list(sent_main)[-500:], list(sent_nr)[-500:]
    save_state(st)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    logging.info("🚀 SSC monitor started (proxy+BS4 mode)")
    while True:
        try: cycle()
        except Exception as e: logging.error("Cycle crashed → %s", e)
        time.sleep(CHECK_INTERVAL)
