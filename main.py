#!/usr/bin/env python3
"""
Multi-SSC Monitor – proxy + BeautifulSoup version
"""

import os, re, json, time, logging, requests
from datetime import datetime, timedelta
from dateutil.parser import parse as dtparse

import html_scraper                       # ← changed import

MAIN_SSC_API = ("https://ssc.gov.in/api/public/noticeboard"
                "?page=0&size=50&sort=createdOn,desc")
SSC_NR_URL   = "https://sscnr.nic.in/newlook/site/Whatsnew.html"
DATE_RE_NR   = re.compile(r"\[(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\]")

STATE_FILE   = "/data/multi_ssc_state.json"
LOOKBACK_DAYS = 12
CHECK_INTERVAL = 300  # s

# … (helper functions stay the same) …

# ── MAIN SSC combined scraper ────────────────────────────────
def scrape_main():
    try:
        return scrape_main_api()
    except Exception as e:
        logging.warning("API failed → %s – falling back to HTML", e)
        return html_scraper.scrape_main_html()   # ← call via module
