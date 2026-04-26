# -*- coding: ascii -*-
"""
CWO SPC Daily Outlook Emailer v9.2 (FIXED)
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

# ✅ ALWAYS latest Day 1 image
DAY1_IMG = "https://www.spc.noaa.gov/products/outlook/day1otlk.gif"

# CWO bounding box
CWO_XMIN, CWO_XMAX = -91.5, -86.5
CWO_YMIN, CWO_YMAX = 40.5, 44.0

FEATURE_BASE = (
    "https://mapservices.weather.noaa.gov"
    "/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"
)

LAYER_CAT  = 1
LAYER_TORN = 2
LAYER_WIND = 3
LAYER_HAIL = 4

CAT_ORDER = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]

CAT_NUM_MAP = {
    "2": "TSTM",
    "3": "MRGL",
    "4": "SLGT",
    "5": "ENH",
    "6": "MDT",
    "8": "HIGH",
}

VALID_PROBS = {2,5,10,15,30,45,60,75,90}

# -----------------------------------------------------------------------------

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "CWO"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def fetch_json(url):
    return json.loads(fetch_text(url))

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
        feats = data.get("features", [])
        return [f.get("attributes", {}) for f in feats]
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

# ✅ FIXED PROBABILITY PARSER
def best_prob(feats, prob_map, layer_name=""):
    vals = []

    for f in feats:
        for field, val in f.items():

            if val is None:
                continue

            raw = str(val).strip().replace("%", "")

            try:
                if raw.startswith("0."):
                    pct = int(round(float(raw) * 100))
                else:
                    pct = int(round(float(raw)))
            except:
                continue

            if pct in prob_map.values():
                vals.append(pct)

    if vals:
        return max(vals)

    return 0

# -----------------------------------------------------------------------------

def get_cwo_risks():
    cat_feats  = query_layer(LAYER_CAT)
    torn_feats = query_layer(LAYER_TORN)
    wind_feats = query_layer(LAYER_WIND)
    hail_feats = query_layer(LAYER_HAIL)

    return {
        "cat_key": best_cat_key(cat_feats),
        "torn":    best_prob(torn_feats, VALID_PROBS, "Tornado"),
        "wind":    best_prob(wind_feats, VALID_PROBS, "Wind"),
        "hail":    best_prob(hail_feats, VALID_PROBS, "Hail"),
    }

# -----------------------------------------------------------------------------

def build_html(cwo):

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    def pct(p):
        return f"{p}%" if p else "Less than 2%"

    out  = "<html><body style='font-family:Arial;background:#eef0f5;'>"
    out += "<div style='max-width:700px;margin:auto;background:white;padding:20px;'>"

    out += "<h2>Nado Nomad's Convective Compass</h2>"
    out += "<p>" + now_utc + "</p>"

    # ✅ IMAGE INSERTED (no layout break)
    out += "<h3>Day 1 Outlook</h3>"
    out += f"<img src='{DAY1_IMG}' style='width:100%;border-radius:6px;'>"

    out += "<h3>CWO Area Risk</h3>"
    out += f"<p><b>Categorical:</b> {cwo['cat_key']}</p>"

    out += "<p>"
    out += f"Tornado: {pct(cwo['torn'])}<br>"
    out += f"Wind: {pct(cwo['wind'])}<br>"
    out += f"Hail: {pct(cwo['hail'])}"
    out += "</p>"

    out += "</div></body></html>"

    return out

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

    cwo = get_cwo_risks()

    subject = f"CWO Outlook | Tor {cwo['torn']}% | Wind {cwo['wind']}%"

    html = build_html(cwo)

    send_email(subject, html)

# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
