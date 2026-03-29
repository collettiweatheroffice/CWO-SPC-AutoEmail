"""
CWO SPC Daily Outlook Emailer v4
Colletti Weather Office - LOT / MKX / DVN
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

# ── CONFIG ─────────────────────────────────────────────────────────────────────
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"
UNSUB_URL  = "https://forms.gle/Jg5opiANhsZfBGYT9"
YT_URL     = "https://www.youtube.com/@MidwestMeteorology"

SPC_BASE   = "https://www.spc.noaa.gov"

# CWO bounding box: LOT + MKX + DVN combined (lon/lat)
CWO_XMIN, CWO_XMAX = -91.5, -86.5
CWO_YMIN, CWO_YMAX =  40.5,  44.0

# Raw text product endpoints (tgftp — always available)
TEXT_URLS = {
    1: "https://tgftp.nws.noaa.gov/data/raw/ac/acus01.kwns.swo.dy1.txt",
    2: "https://tgftp.nws.noaa.gov/data/raw/ac/acus02.kwns.swo.dy2.txt",
    3: "https://tgftp.nws.noaa.gov/data/raw/ac/acus03.kwns.swo.dy3.txt",
}

# SPC FeatureServer layer IDs (mapservices.weather.noaa.gov)
# Layer 1  = Day 1 Categorical
# Layer 3  = Day 1 Probabilistic Tornado
# Layer 4  = Day 1 Probabilistic Wind (index 4 in FeatureServer = layer 4)
# Layer 5  = Day 1 Probabilistic Hail
# Layer 9  = Day 2 Categorical
# Layer 16 = Day 3 Categorical
FEATURE_BASE = "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"

# Outlook page links for "View" buttons
OUTLOOK_PAGES = {
    1: f"{SPC_BASE}/products/outlook/day1otlk.html",
    2: f"{SPC_BASE}/products/outlook/day2otlk.html",
    3: f"{SPC_BASE}/products/outlook/day3otlk.html",
}

# Categorical risk label map (dn field values from NOAA FeatureServer)
CAT_LABELS = {
    "TSTM":   "⚪ General Thunderstorms",
    "MRGL":   "🟢 Marginal Risk",
    "SLGT":   "🟡 Slight Risk",
    "ENH":    "🟡 Enhanced Risk",
    "MDT":    "🟠 Moderate Risk",
    "HIGH":   "🔴 High Risk",
    "SIGN":   "🔴 Significant (Hatched)",
}

PROB_LABELS = {
    "0.02": "2%", "0.05": "5%", "0.10": "10%", "0.15": "15%",
    "0.30": "30%", "0.45": "45%", "0.60": "60%",
    "2":  "2%",  "5":  "5%",  "10": "10%", "15": "15%",
    "30": "30%", "45": "45%", "60": "60%",
}
# ───────────────────────────────────────────────────────────────────────────────


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/4.0 (collettiweather@gmail.com)",
        "Accept": "text/plain, text/html, application/json, application/geo+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url):
    return json.loads(fetch(url))


# ── TEXT PRODUCT PARSING ───────────────────────────────────────────────────────

def get_outlook_text(day=1):
    """Fetch raw SPC convective outlook text from tgftp."""
    url = TEXT_URLS.get(day, "")
    try:
        raw = fetch(url)
        lines = raw.splitlines()
        body, in_body = [], False
        for line in lines:
            if re.match(r"SWODY\d", line.strip()):
                in_body = True
                continue
            if in_body:
                body.append(line)
        text = "\n".join(body).strip()
        text = re.sub(r"\$\$.*", "", text, flags=re.DOTALL).strip()
        return text if text else raw[:3000]
    except Exception as e:
        return f"[Could not retrieve Day {day} text: {e}]"


def get_national_category(text):
    """Parse the highest national risk from text."""
    upper = text.upper()
    for keyword, label in [
        ("PARTICULARLY DANGEROUS SITUATION", "🔴 PDS — Particularly Dangerous Situation"),
        ("HIGH RISK",     "🔴 High Risk"),
        ("MODERATE RISK", "🟠 Moderate Risk"),
        ("ENHANCED RISK", "🟡 Enhanced Risk"),
        ("SLIGHT RISK",   "🟡 Slight Risk"),
        ("MARGINAL RISK", "🟢 Marginal Risk"),
        ("THUNDERSTORMS", "⚪ General Thunderstorms"),
    ]:
        if keyword in upper:
            return label
    return "⚪ No Thunder / Below Threshold"


def extract_section(text, keyword):
    """Pull a named hazard section from text."""
    m = re.search(
        rf"\.\.\.{keyword}\.\.\..*?(?=\.\.\.[A-Z]{{3,}}\.\.\.|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        s = m.group(0).strip()
        return (s[:700] + "...") if len(s) > 700 else s
    return f"No {keyword.lower()} section found in this outlook."


# ── GEOJSON AREA RISK CHECK ────────────────────────────────────────────────────

def query_feature_layer(layer_id, geometry_envelope):
    """
    Query a NOAA FeatureServer layer for features intersecting a bounding box.
    Returns list of feature attribute dicts.
    """
    params = urllib.parse.urlencode({
        "geometry": geometry_envelope,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    })
    url = f"{FEATURE_BASE}/{layer_id}/query?{params}"
    try:
        data = fetch_json(url)
        features = data.get("features", [])
        return [f.get("attributes", {}) for f in features]
    except Exception as e:
        print(f"[CWO] FeatureServer layer {layer_id} query failed: {e}")
        return []


def get_cwo_area_risks():
    """
    Query NOAA FeatureServer for risk levels overlapping the CWO bounding box.
    Returns a dict with categorical and prob risk strings for each hazard.
    """
    envelope = f"{CWO_XMIN},{CWO_YMIN},{CWO_XMAX},{CWO_YMAX}"

    results = {
        "cat":  "Not available",
        "torn": "Not available",
        "wind": "Not available",
        "hail": "Not available",
    }

    # Day 1 Categorical (layer 1)
    cat_feats = query_feature_layer(1, envelope)
    if cat_feats:
        # Pick highest risk
        order = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]
        found = set(str(f.get("dn", "")).upper() for f in cat_feats)
        for level in order:
            if level in found:
                results["cat"] = CAT_LABELS.get(level, level)
                break
        if results["cat"] == "Not available":
            results["cat"] = "⚪ No Thunder / Below Threshold"
    else:
        results["cat"] = "⚪ No Thunder / Below Threshold"

    # Day 1 Probabilistic Tornado (layer 3)
    torn_feats = query_feature_layer(3, envelope)
    if torn_feats:
        probs = []
        for f in torn_feats:
            dn = str(f.get("dn", f.get("DN", ""))).strip()
            label = PROB_LABELS.get(dn, dn)
            if label:
                probs.append(label)
        if probs:
            results["torn"] = f"Up to {max(probs, key=lambda x: float(x.replace('%','')))} tornado probability over CWO area"
        else:
            results["torn"] = "< 2% (no tornado probability contour over CWO area)"
    else:
        results["torn"] = "< 2% (no tornado probability contour over CWO area)"

    # Day 1 Probabilistic Wind (layer 4)
    wind_feats = query_feature_layer(4, envelope)
    if wind_feats:
        probs = []
        for f in wind_feats:
            dn = str(f.get("dn", f.get("DN", ""))).strip()
            label = PROB_LABELS.get(dn, dn)
            if label:
                probs.append(label)
        if probs:
            results["wind"] = f"Up to {max(probs, key=lambda x: float(x.replace('%','')))} wind probability over CWO area"
        else:
            results["wind"] = "< 5% (no wind probability contour over CWO area)"
    else:
        results["wind"] = "< 5% (no wind probability contour over CWO area)"

    # Day 1 Probabilistic Hail (layer 5)
    hail_feats = query_feature_layer(5, envelope)
    if hail_feats:
        probs = []
        for f in hail_feats:
            dn = str(f.get("dn", f.get("DN", ""))).strip()
            label = PROB_LABELS.get(dn, dn)
            if label:
                probs.append(label)
        if probs:
            results["hail"] = f"Up to {max(probs, key=lambda x: float(x.replace('%','')))} hail probability over CWO area"
        else:
            results["hail"] = "< 5% (no hail probability contour over CWO area)"
    else:
        results["hail"] = "< 5% (no hail probability contour over CWO area)"

    return results


# ── MESOSCALE DISCUSSIONS ──────────────────────────────────────────────────────

def get_active_mds():
    results = []
    try:
        data = fetch_json("https://api.weather.gov/products/types/MCD/locations/KWNS?limit=10")
        for p in data.get("@graph", []):
            num_m = re.search(r"MCD\s*(\d+)", p.get("productName", ""), re.IGNORECASE)
            num   = num_m.group(1) if num_m else "???"
            results.append({
                "num":   num,
                "title": p.get("productName", f"Mesoscale Discussion #{num}"),
                "url":   f"{SPC_BASE}/products/md/md{num.zfill(4)}.html",
                "time":  p.get("issuanceTime", "")[:10],
            })
    except Exception as e:
        print(f"[CWO] NWS API MD failed: {e} — trying SPC scrape")
        try:
            html  = fetch(f"{SPC_BASE}/products/md/")
            links = re.findall(r'href="[./]*/products/md/(md\d+\.html)"', html)
            seen  = set()
            for link in links[:8]:
                num_m = re.search(r"md(\d+)\.html", link)
                num   = (num_m.group(1).lstrip("0") or "0") if num_m else "???"
                if num in seen:
                    continue
                seen.add(num)
                results.append({
                    "num":   num,
                    "title": f"Mesoscale Discussion #{num}",
                    "url":   f"{SPC_BASE}/products/md/md{num.zfill(4)}.html",
                    "time":  "",
                })
        except Exception as e2:
            print(f"[CWO] SPC MD scrape also failed: {e2}")
    return results


# ── EMAIL BUILD ────────────────────────────────────────────────────────────────

def build_html(day1_text, day2_text, day3_text, cwo_risks, mds):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    nat1 = get_national_category(day1_text)
    nat2 = get_national_category(day2_text)
    nat3 = get_national_category(day3_text)

    torn_txt  = extract_section(day1_text, "TORNADO")
    wind_txt  = extract_section(day1_text, "WIND")
    hail_txt  = extract_section(day1_text, "HAIL")
    tstm_txt  = extract_section(day1_text, "THUNDERSTORMS")
    summary   = day1_text[:1400].strip()

    # MDs
    if mds:
        md_rows = "".join(f"""
        <tr style="border-bottom:1px solid #f0e8c8;">
          <td style="padding:8px 12px;font-size:13px;color:#7a5200;font-weight:700;">#{m['num']}</td>
          <td style="padding:8px 12px;font-size:13px;">
            <a href="{m['url']}" style="color:#1a3a5c;text-decoration:none;">{m['title']}</a>
          </td>
          <td style="padding:8px 12px;font-size:12px;color:#999;">{m['time']}</td>
        </tr>""" for m in mds)
        md_html = f"""
        <table style="width:100%;border-collapse:collapse;background:#fffdf2;border-radius:6px;overflow:hidden;border:1px solid #f0e8c8;">
          <tr style="background:#fff3cd;">
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#7a5200;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">MD #</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#7a5200;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">Title</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#7a5200;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">Date</th>
          </tr>
          {md_rows}
        </table>"""
    else:
        md_html = "<p style='color:#888;font-style:italic;font-size:13px;margin:0;'>No active mesoscale discussions at time of send.</p>"

    # SPC link buttons
    btns = ""
    for name, url in [
        ("Day 1 Outlook",     OUTLOOK_PAGES[1]),
        ("Day 2 Outlook",     OUTLOOK_PAGES[2]),
        ("Day 3 Outlook",     OUTLOOK_PAGES[3]),
        ("Tornado Prob",      f"{SPC_BASE}/products/outlook/day1probotlk.html#torn"),
        ("Wind Prob",         f"{SPC_BASE}/products/outlook/day1probotlk.html#wind"),
        ("Hail Prob",         f"{SPC_BASE}/products/outlook/day1probotlk.html#hail"),
        ("Active MDs",        f"{SPC_BASE}/products/md/"),
        ("SPC Homepage",      SPC_BASE),
    ]:
        btns += f'<a href="{url}" style="display:inline-block;margin:4px 5px 4px 0;padding:7px 13px;background:#1a1f5e;color:#d4a843;border-radius:5px;font-size:12px;font-weight:700;text-decoration:none;">{name}</a>'

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eef0f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:680px;margin:0 auto;">

  <!-- HEADER -->
  <div style="background:#1a1f5e;padding:28px 28px 22px;text-align:center;">
    <img src="cid:cwo_logo" alt="Colletti Weather Office"
         style="max-width:130px;height:auto;display:block;margin:0 auto 14px;" />
    <h1 style="margin:0;color:#d4a843;font-size:20px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;">
      Daily SPC Outlook Brief
    </h1>
    <p style="margin:6px 0 2px;color:#8fa8d8;font-size:13px;">
      NWS Chicago (LOT) &nbsp;·&nbsp; NWS Milwaukee (MKX) &nbsp;·&nbsp; NWS Quad Cities (DVN)
    </p>
    <p style="margin:0;color:#5566aa;font-size:11px;">{now_utc}</p>
  </div>

  <!-- NATIONAL CATEGORICAL -->
  <div style="background:#fff;margin:14px 14px 0;border-radius:8px;padding:20px 22px;border-top:4px solid #1a1f5e;">
    <h2 style="margin:0 0 14px;font-size:14px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">
      📊 National Categorical Risk
    </h2>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;width:110px;">Day 1 Outlook</td>
        <td style="padding:10px 14px;font-size:14px;">{nat1}</td>
        <td style="padding:10px 14px;text-align:right;"><a href="{OUTLOOK_PAGES[1]}" style="font-size:11px;color:#1a3a5c;text-decoration:none;">View ↗</a></td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 2 Outlook</td>
        <td style="padding:10px 14px;font-size:14px;">{nat2}</td>
        <td style="padding:10px 14px;text-align:right;"><a href="{OUTLOOK_PAGES[2]}" style="font-size:11px;color:#1a3a5c;text-decoration:none;">View ↗</a></td>
      </tr>
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 3 Outlook</td>
        <td style="padding:10px 14px;font-size:14px;">{nat3}</td>
        <td style="padding:10px 14px;text-align:right;"><a href="{OUTLOOK_PAGES[3]}" style="font-size:11px;color:#1a3a5c;text-decoration:none;">View ↗</a></td>
      </tr>
    </table>
  </div>

  <!-- CWO AREA RISKS -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;border-top:4px solid #d4a843;">
    <h2 style="margin:0 0 14px;font-size:14px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">
      📍 CWO Area Risk (LOT / MKX / DVN)
    </h2>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:13px;width:130px;">Categorical</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['cat']}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#c0392b;font-size:13px;">🌪️ Tornado</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['torn']}</td>
      </tr>
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#2471a3;font-size:13px;">💨 Wind</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['wind']}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#1e8449;font-size:13px;">🧊 Hail</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['hail']}</td>
      </tr>
    </table>
    <p style="font-size:11px;color:#aaa;margin:10px 0 0;">Based on SPC probability contours intersecting LOT/MKX/DVN bounding box.</p>
  </div>

  <!-- HAZARD TEXT SECTIONS -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 14px;font-size:14px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">
      ⚡ Day 1 Outlook Hazard Text
    </h2>

    <p style="font-weight:700;color:#c0392b;font-size:13px;margin:0 0 4px;">🌪️ TORNADO</p>
    <pre style="background:#fdf2f0;border-left:3px solid #c0392b;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;color:#333;line-height:1.6;font-family:monospace;">{torn_txt}</pre>

    <p style="font-weight:700;color:#2471a3;font-size:13px;margin:0 0 4px;">💨 WIND</p>
    <pre style="background:#eaf4fb;border-left:3px solid #2471a3;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;color:#333;line-height:1.6;font-family:monospace;">{wind_txt}</pre>

    <p style="font-weight:700;color:#1e8449;font-size:13px;margin:0 0 4px;">🧊 HAIL</p>
    <pre style="background:#eafaf1;border-left:3px solid #1e8449;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;color:#333;line-height:1.6;font-family:monospace;">{hail_txt}</pre>

    <p style="font-weight:700;color:#6c3483;font-size:13px;margin:0 0 4px;">⛈️ THUNDERSTORMS</p>
    <pre style="background:#f5eef8;border-left:3px solid #6c3483;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0;color:#333;line-height:1.6;font-family:monospace;">{tstm_txt}</pre>
  </div>

  <!-- FULL DAY 1 TEXT -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 12px;font-size:14px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">
      📋 Day 1 Outlook Full Text
    </h2>
    <pre style="background:#f4f6f8;padding:14px;font-size:12px;white-space:pre-wrap;border-radius:6px;margin:0;color:#222;line-height:1.65;font-family:monospace;">{summary}</pre>
    <p style="font-size:12px;color:#888;margin:8px 0 0;">
      Full product: <a href="{OUTLOOK_PAGES[1]}" style="color:#1a3a5c;">SPC Day 1 Outlook ↗</a>
    </p>
  </div>

  <!-- MDs -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 12px;font-size:14px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">
      🔍 Active Mesoscale Discussions
    </h2>
    {md_html}
    <p style="font-size:12px;color:#888;margin:10px 0 0;">
      <a href="{SPC_BASE}/products/md/" style="color:#1a3a5c;">All active MDs on SPC ↗</a>
    </p>
  </div>

  <!-- SPC LINKS -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 10px;font-size:14px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">
      🗺️ SPC Links
    </h2>
    {btns}
  </div>

  <!-- FOOTER -->
  <div style="background:#1a1f5e;margin:14px 14px 0;border-radius:8px;padding:22px 24px;text-align:center;">
    <p style="margin:0 0 4px;color:#d4a843;font-weight:700;font-size:15px;letter-spacing:0.5px;">
      Colletti Weather Office
    </p>
    <p style="margin:0 0 4px;color:#8fa8d8;font-size:12px;">
      <a href="mailto:{REPLY_TO}" style="color:#aac4ee;">{REPLY_TO}</a>
    </p>
    <p style="margin:0 0 14px;">
      <a href="{YT_URL}" style="color:#d4a843;font-size:13px;font-weight:700;text-decoration:none;">
        ▶ YouTube.com/@MidwestMeteorology
      </a>
    </p>
    <hr style="border:none;border-top:1px solid #2a3270;margin:12px 0;" />
    <p style="margin:0;color:#5566aa;font-size:11px;line-height:1.8;">
      You are subscribed to CWO weather alerts.<br>
      Per federal law (CAN-SPAM Act), you may unsubscribe at any time.<br>
      <a href="{UNSUB_URL}" style="color:#aac4ee;">Click here to unsubscribe</a>
    </p>
    <p style="margin:8px 0 0;color:#3a4488;font-size:10px;">
      Automated digest — always verify with official NWS/SPC products.
    </p>
  </div>
  <div style="height:18px;"></div>

</div>
</body></html>"""


# ── SEND ───────────────────────────────────────────────────────────────────────

def send_email(subject, html_body):
    msg = MIMEMultipart("related")
    msg["Subject"]  = subject
    msg["From"]     = GMAIL_USER
    msg["To"]       = TO_EMAIL
    msg["Reply-To"] = REPLY_TO

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # Attach logo from repo root (must be named cwo_logo.png)
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cwo_logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            img = MIMEImage(f.read())
        img.add_header("Content-ID", "<cwo_logo>")
        img.add_header("Content-Disposition", "inline", filename="cwo_logo.png")
        msg.attach(img)
        print("[CWO] Logo attached.")
    else:
        print(f"[CWO] WARNING: logo not found at {logo_path}")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"[CWO] Email sent to {TO_EMAIL}")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    print("[CWO] Fetching outlook texts...")
    day1_text = get_outlook_text(1)
    day2_text = get_outlook_text(2)
    day3_text = get_outlook_text(3)
    print(f"[CWO] Day 1 national: {get_national_category(day1_text)}")

    print("[CWO] Querying CWO area risks via NOAA FeatureServer...")
    cwo_risks = get_cwo_area_risks()
    print(f"[CWO] CWO categorical: {cwo_risks['cat']}")
    print(f"[CWO] CWO tornado: {cwo_risks['torn']}")

    print("[CWO] Fetching MDs...")
    mds = get_active_mds()
    print(f"[CWO] {len(mds)} active MD(s)")

    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nat1      = get_national_category(day1_text)
    subject   = f"[CWO] SPC Brief — {now_str} | Day 1: {nat1} | CWO: {cwo_risks['cat']}"

    html = build_html(day1_text, day2_text, day3_text, cwo_risks, mds)
    send_email(subject, html)
    print("[CWO] Done.")


if __name__ == "__main__":
    main()
