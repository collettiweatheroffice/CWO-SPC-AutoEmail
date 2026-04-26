# -*- coding: ascii -*-
"""
CWO SPC Daily Outlook Emailer v10.0
Colletti Weather Office
"""

import smtplib
import urllib.request
import urllib.parse
import json
import re
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timezone

# -- CONFIG -------------------------------------------------------------------
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"

SPC_BASE = "https://www.spc.noaa.gov"

# ALWAYS latest Day 1 image (auto updates by SPC)
DAY1_IMG = "https://www.spc.noaa.gov/products/outlook/day1otlk.gif"

# CWO bounding box
CWO_XMIN, CWO_XMAX = -91.5, -86.5
CWO_YMIN, CWO_YMAX = 40.5, 44.0

TEXT_URLS = {
    1: "https://tgftp.nws.noaa.gov/data/raw/ac/acus01.kwns.swo.dy1.txt",
    2: "https://tgftp.nws.noaa.gov/data/raw/ac/acus02.kwns.swo.dy2.txt",
    3: "https://tgftp.nws.noaa.gov/data/raw/ac/acus03.kwns.swo.dy3.txt",
}

FEATURE_BASE = "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"

LAYER_CAT  = 1
LAYER_TORN = 2
LAYER_WIND = 3
LAYER_HAIL = 4

CAT_ORDER = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]

CAT_NUM_MAP = {
    "2": "TSTM", "3": "MRGL", "4": "SLGT",
    "5": "ENH", "6": "MDT", "8": "HIGH",
}

# Allowed SPC probabilities
VALID_PROBS = {2,5,10,15,30,45,60,75,90}

# -----------------------------------------------------------------------------

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "CWO"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def fetch_json(url):
    return json.loads(fetch_text(url))

# -----------------------------------------------------------------------------

def get_outlook_text(day):
    try:
        raw = fetch_text(TEXT_URLS[day])
        lines = raw.splitlines()
        body, grab = [], False
        for l in lines:
            if re.match(r"SWODY\d", l.strip()):
                grab = True
                continue
            if grab:
                body.append(l)
        return "\n".join(body)
    except:
        return "Text unavailable"

# -----------------------------------------------------------------------------

def query_layer(layer_id):
    envelope = f"{CWO_XMIN},{CWO_YMIN},{CWO_XMAX},{CWO_YMAX}"
    params = urllib.parse.urlencode({
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json"
    })
    url = f"{FEATURE_BASE}/{layer_id}/query?{params}"

    try:
        data = fetch_json(url)
        return [f.get("attributes", {}) for f in data.get("features", [])]
    except:
        return []

# -----------------------------------------------------------------------------

def best_cat_key(feats):
    found = set()
    for f in feats:
        raw = str(f.get("dn", "")).strip()
        if raw in CAT_NUM_MAP:
            found.add(CAT_NUM_MAP[raw])

    for lvl in CAT_ORDER:
        if lvl in found:
            return lvl
    return None

# FIXED PROBABILITY PARSER
def best_prob(feats, name=""):
    vals = []

    for f in feats:
        for v in f.values():
            if v is None:
                continue

            raw = str(v).replace("%", "").strip()

            try:
                if raw.startswith("0."):
                    pct = int(float(raw) * 100)
                else:
                    pct = int(float(raw))
            except:
                continue

            if pct in VALID_PROBS:
                vals.append(pct)

    return max(vals) if vals else 0

# -----------------------------------------------------------------------------

def get_cwo_risks():
    cat_feats  = query_layer(LAYER_CAT)
    torn_feats = query_layer(LAYER_TORN)
    wind_feats = query_layer(LAYER_WIND)
    hail_feats = query_layer(LAYER_HAIL)

    return {
        "cat":  best_cat_key(cat_feats),
        "torn": best_prob(torn_feats, "tornado"),
        "wind": best_prob(wind_feats, "wind"),
        "hail": best_prob(hail_feats, "hail"),
    }

# -----------------------------------------------------------------------------

def build_html(day1_text, cwo):

    def pct(p):
        return f"{p}%" if p else "<2%"

    html = f"""
    <html>
    <body style="font-family:Arial;background:#eef0f5;padding:10px;">

    <div style="max-width:700px;margin:auto;background:white;padding:20px;border-radius:8px;">

    <h2>Nado Nomad's Convective Compass</h2>

    <p><b>Latest SPC Day 1 Outlook</b></p>
    <img src="{DAY1_IMG}" style="width:100%;border-radius:6px;"><br><br>

    <h3>CWO Area Risk</h3>
    <p><b>Categorical:</b> {cwo['cat']}</p>

    <p>Tornado: {pct(cwo['torn'])}<br>
    Wind: {pct(cwo['wind'])}<br>
    Hail: {pct(cwo['hail'])}</p>

    <h3>Day 1 Discussion</h3>
    <pre style="white-space:pre-wrap;font-size:12px;">{day1_text[:2000]}</pre>

    </div>
    </body>
    </html>
    """

    return html

# -----------------------------------------------------------------------------

def send_email(subject, html):

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = TO_EMAIL

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASS)
        s.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())

# -----------------------------------------------------------------------------

def main():

    day1 = get_outlook_text(1)
    cwo  = get_cwo_risks()

    subject = f"CWO Outlook | Tornado {cwo['torn']}% | Wind {cwo['wind']}%"

    html = build_html(day1, cwo)
    send_email(subject, html)

# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
