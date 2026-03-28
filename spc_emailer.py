"""
CWO SPC Daily Outlook Emailer v2.2
Proprietary Code - Copyright (c) 2026 Jonathan Colletti
Authorized Use: Colletti Weather Office
"""

import smtplib
import urllib.request
import json
import re
import os
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

# --- CONFIG ---
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"

# CWO coverage bounding box (LOT + MKX + DVN)
LAT_MIN, LAT_MAX = 40.5, 44.0
LON_MIN, LON_MAX = -91.5, -86.5

SPC_BASE = "https://www.spc.noaa.gov"
MD_JSON_URL = f"https://www.spc.noaa.gov?{int(time.time())}"

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "CWO-SPC-Emailer/2.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def get_central_timestamp():
    """Generates the requested CWO: [DATE] [TIME] format in Central Time."""
    # This assumes the GitHub runner or system has access to UTC
    # We manually offset for Central (CDT is UTC-5, CST is UTC-6)
    # For a more robust version in GitHub Actions, use 'pytz' if available
    now_utc = datetime.now(timezone.utc)
    # Simple manual offset for Central Daylight Time (March-Nov)
    # Adjust to -6 for Standard Time if needed
    from datetime import timedelta
    central_time = now_utc - timedelta(hours=5) 
    return central_time.strftime("%m/%d/%Y %I:%M %p CT")

def get_outlook_text(day=1):
    text_url = f"{SPC_BASE}/products/outlook/day{day}otlk_txt.html"
    try:
        raw = fetch(text_url)
        clean = re.sub(r"<[^>]+>", "", raw)
        # Targeted regex for the SUMMARY section
        match = re.search(r"(SUMMARY.*?)(\$\$)", clean, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return clean[:2000]
    except Exception as e:
        return f"[Could not retrieve Day {day} outlook: {e}]"

def get_outlook_category(day=1):
    text = get_outlook_text(day)
    categories = [
        ("PARTICULARLY DANGEROUS SITUATION", "🔴 PDS — Particularly Dangerous Situation"),
        ("HIGH RISK",    "🔴 HIGH RISK"),
        ("MODERATE RISK","🟠 MODERATE RISK"),
        ("ENHANCED RISK","🟡 ENHANCED RISK"),
        ("SLIGHT RISK",  "🟡 SLIGHT RISK"),
        ("MARGINAL RISK","🟢 MARGINAL RISK"),
        ("ANY",          "🟢 MARGINAL / ANY RISK AREA"),
        ("POINTS",       "🟢 RISK AREA DEFINED"),
        ("THUNDERSTORMS","⚪ GENERAL THUNDERSTORMS"),
    ]
    upper = text.upper()
    for keyword, label in categories:
        if keyword in upper:
            return label, text
    return "⚪ NO THUNDER / BELOW THRESHOLD", text

def get_graphic_links():
    return {
        "Day 1 Outlook": f"{SPC_BASE}/products/outlook/day1otlk.html",
        "Day 2 Outlook": f"{SPC_BASE}/products/outlook/day2otlk.html",
        "Day 3 Outlook": f"{SPC_BASE}/products/outlook/day3otlk.html",
        "Mesoscale MDs": f"{SPC_BASE}/products/md/",
    }

def send_email():
    day1_cat, day1_text = get_outlook_category(1)
    day2_cat, _ = get_outlook_category(2)
    day3_cat, _ = get_outlook_category(3)
    graphics = get_graphic_links()
    
    subject_ts = get_central_timestamp()
    
    msg = MIMEMultipart()
    msg["From"] = f"Colletti Weather Office <{GMAIL_USER}>"
    msg["To"] = TO_EMAIL
    msg["Subject"] = f"CWO: {subject_ts} SPC Outlook Summary"
    msg["Reply-To"] = REPLY_TO

    # [Insert your existing build_email_html logic here to create 'body']
    # body = build_email_html(day1_cat, day1_text, day2_cat, day3_cat, ...)
    
    # Placeholder for sending (ensure your SMTP logic remains below)
    # server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    # ...
    print(f"Subject prepared: {msg['Subject']}")

if __name__ == "__main__":
    send_email()
