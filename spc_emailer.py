"""
CWO SPC Daily Outlook Emailer v6
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

# -- CONFIG ---------------------------------------------------------------------
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"
UNSUB_URL  = "https://forms.gle/Jg5opiANhsZfBGYT9"
YT_URL     = "https://www.youtube.com/@MidwestMeteorology"

SPC_BASE   = "https://www.spc.noaa.gov"

# CWO bounding box: LOT + MKX + DVN combined
CWO_XMIN, CWO_XMAX = -91.5, -86.5
CWO_YMIN, CWO_YMAX =  40.5,  44.0

# Raw text product endpoints (tgftp - always works)
TEXT_URLS = {
    1: "https://tgftp.nws.noaa.gov/data/raw/ac/acus01.kwns.swo.dy1.txt",
    2: "https://tgftp.nws.noaa.gov/data/raw/ac/acus02.kwns.swo.dy2.txt",
    3: "https://tgftp.nws.noaa.gov/data/raw/ac/acus03.kwns.swo.dy3.txt",
}

# Outlook page links
OUTLOOK_PAGES = {
    1: f"{SPC_BASE}/products/outlook/day1otlk.html",
    2: f"{SPC_BASE}/products/outlook/day2otlk.html",
    3: f"{SPC_BASE}/products/outlook/day3otlk.html",
}

# SPC issuance times (UTC) - convective outlook GIF naming convention
# SPC issues at 0100Z, 1200Z, 1630Z, 2000Z
ISSUANCE_TIMES = ["2000", "1630", "1200", "0100"]

# Thunderstorm outlook (enhanced thunderstorm outlook) image URL
TSTM_OUTLOOK_URL = f"{SPC_BASE}/products/exper/enhtstm/imgs/enhtstm.gif"
TSTM_OUTLOOK_PAGE = f"{SPC_BASE}/products/exper/enhtstm/"

# NOAA FeatureServer for area-specific risk
FEATURE_BASE = "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"

CAT_ORDER  = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]
CAT_LABELS = {
    "HIGH": "&#128308; High Risk",
    "MDT":  "&#128992; Moderate Risk",
    "ENH":  "&#128993; Enhanced Risk",
    "SLGT": "&#128993; Slight Risk",
    "MRGL": "&#128994; Marginal Risk",
    "TSTM": "&#9898; General Thunderstorms",
}
PROB_VALUES = {
    "2": 2, "5": 5, "10": 10, "15": 15, "30": 30, "45": 45, "60": 60,
    "0.02": 2, "0.05": 5, "0.10": 10, "0.15": 15, "0.30": 30, "0.45": 45, "0.60": 60,
}
# -------------------------------------------------------------------------------


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/6.0 (collettiweather@gmail.com)",
        "Accept": "text/plain, text/html, application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/6.0 (collettiweather@gmail.com)",
        "Accept": "image/gif, image/png, image/jpeg, image/*",
        "Referer": "https://www.spc.noaa.gov/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url):
    return json.loads(fetch_text(url))


# -- OUTLOOK TEXT ---------------------------------------------------------------

def get_outlook_text(day=1):
    try:
        raw   = fetch_text(TEXT_URLS[day])
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
    upper = text.upper()
    for kw, label in [
        ("PARTICULARLY DANGEROUS SITUATION", "&#128308; PDS -- Particularly Dangerous Situation"),
        ("HIGH RISK",     "&#128308; High Risk"),
        ("MODERATE RISK", "&#128992; Moderate Risk"),
        ("ENHANCED RISK", "&#128993; Enhanced Risk"),
        ("SLIGHT RISK",   "&#128993; Slight Risk"),
        ("MARGINAL RISK", "&#128994; Marginal Risk"),
        ("THUNDERSTORMS", "&#9898; General Thunderstorms"),
    ]:
        if kw in upper:
            return label
    return "&#9898; No Thunder / Below Threshold"


def extract_section(text, keyword):
    m = re.search(
        rf"\.\.\.{keyword}\.\.\..*?(?=\.\.\.[A-Z]{{3,}}\.\.\.|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        s = m.group(0).strip()
        return (s[:700] + "...") if len(s) > 700 else s
    return f"No {keyword.lower()} section found in this outlook."


# -- IMAGE FETCHING -------------------------------------------------------------

def fetch_convective_outlook_image():
    """
    Download the SPC Day 1 convective outlook GIF.
    SPC filenames: day1otlk_HHMM_prt.gif for each issuance time.
    Also tries day1otlk_prt.gif (generic latest).
    """
    candidates = []

    # Generic latest first
    candidates.append(f"{SPC_BASE}/products/outlook/day1otlk_prt.gif")

    # Then try each issuance time (most recent first)
    for hhmm in ISSUANCE_TIMES:
        candidates.append(f"{SPC_BASE}/products/outlook/day1otlk_{hhmm}_prt.gif")

    for url in candidates:
        try:
            data = fetch_bytes(url)
            if data and len(data) > 2000:
                print(f"[CWO] Convective outlook image: {url}")
                return data
        except Exception as e:
            print(f"[CWO] Tried {url}: {e}")
            continue

    print("[CWO] Could not fetch convective outlook image.")
    return None


def fetch_thunderstorm_image():
    """
    Download the SPC enhanced thunderstorm outlook GIF.
    This is a separate product from the convective outlook.
    """
    candidates = [
        TSTM_OUTLOOK_URL,
        f"{SPC_BASE}/products/exper/enhtstm/imgs/enhtstm_latest.gif",
        f"{SPC_BASE}/products/exper/enhtstm/enhtstm.gif",
    ]

    for url in candidates:
        try:
            data = fetch_bytes(url)
            if data and len(data) > 2000:
                print(f"[CWO] Thunderstorm outlook image: {url}")
                return data
        except Exception as e:
            print(f"[CWO] Tried {url}: {e}")
            continue

    print("[CWO] Could not fetch thunderstorm outlook image.")
    return None


# -- CWO AREA RISK --------------------------------------------------------------

def query_layer(layer_id):
    envelope = f"{CWO_XMIN},{CWO_YMIN},{CWO_XMAX},{CWO_YMAX}"
    params = urllib.parse.urlencode({
        "geometry":       envelope,
        "geometryType":   "esriGeometryEnvelope",
        "spatialRel":     "esriSpatialRelIntersects",
        "inSR":           "4326",
        "outFields":      "*",
        "returnGeometry": "false",
        "f":              "json",
    })
    try:
        data = fetch_json(f"{FEATURE_BASE}/{layer_id}/query?{params}")
        return [f.get("attributes", {}) for f in data.get("features", [])]
    except Exception as e:
        print(f"[CWO] Layer {layer_id} failed: {e}")
        return []


def best_cat(feats):
    found = {str(f.get("dn", f.get("DN", ""))).upper() for f in feats}
    for lvl in CAT_ORDER:
        if lvl in found:
            return CAT_LABELS[lvl]
    return "&#9898; No Thunder / Below Threshold"


def best_prob(feats):
    vals = []
    for f in feats:
        raw = str(f.get("dn", f.get("DN", ""))).strip()
        if raw in PROB_VALUES:
            vals.append(PROB_VALUES[raw])
    return max(vals) if vals else 0


def get_cwo_risks():
    cat  = best_cat(query_layer(1))
    torn = best_prob(query_layer(3))
    wind = best_prob(query_layer(4))
    hail = best_prob(query_layer(5))
    return {
        "cat":  cat,
        "torn": f"{torn}% tornado probability over CWO area"  if torn else "< 2% (no contour over CWO area)",
        "wind": f"{wind}% wind probability over CWO area"     if wind else "< 5% (no contour over CWO area)",
        "hail": f"{hail}% hail probability over CWO area"     if hail else "< 5% (no contour over CWO area)",
    }


# -- MESOSCALE DISCUSSIONS ------------------------------------------------------

def get_active_mds():
    """Scrape SPC MD page directly -- most reliable source."""
    results = []
    try:
        html  = fetch_text(f"{SPC_BASE}/products/md/")
        links = re.findall(r'href="(?:\./)?md(\d{4})\.html"', html)
        seen  = set()
        for num in links:
            if num in seen:
                continue
            seen.add(num)
            results.append({
                "num": str(int(num)),
                "url": f"{SPC_BASE}/products/md/md{num}.html",
            })
            if len(results) >= 6:
                break
    except Exception as e:
        print(f"[CWO] MD scrape failed: {e}")
    return results


# -- EMAIL BUILD ----------------------------------------------------------------

def img_block(cid, alt, fallback_url):
    """Inline image block with fallback link."""
    return f"""
    <img src="cid:{cid}" alt="{alt}"
         style="max-width:100%;height:auto;border-radius:6px;
                border:1px solid #ddd;display:block;margin-top:8px;" />
    <p style="font-size:11px;color:#aaa;margin:6px 0 0;text-align:right;">
      <a href="{fallback_url}" style="color:#1a3a5c;">View on SPC &#8599;</a>
    </p>"""


def img_fallback(fallback_url, label):
    return f"""
    <p style="color:#888;font-style:italic;font-size:13px;margin:4px 0;">
      Image unavailable -- <a href="{fallback_url}" style="color:#1a3a5c;">View {label} on SPC &#8599;</a>
    </p>"""


def build_html(day1_text, day2_text, day3_text, cwo_risks, mds,
               has_conv_img, has_tstm_img):

    now_utc  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    nat1     = get_national_category(day1_text)
    nat2     = get_national_category(day2_text)
    nat3     = get_national_category(day3_text)

    torn_txt = extract_section(day1_text, "TORNADO")
    wind_txt = extract_section(day1_text, "WIND")
    hail_txt = extract_section(day1_text, "HAIL")
    tstm_txt = extract_section(day1_text, "THUNDERSTORMS")
    summary  = day1_text[:1400].strip()

    conv_img_html = (img_block("conv_img", "SPC Day 1 Convective Outlook", OUTLOOK_PAGES[1])
                     if has_conv_img else img_fallback(OUTLOOK_PAGES[1], "Convective Outlook"))

    tstm_img_html = (img_block("tstm_img", "SPC Thunderstorm Outlook", TSTM_OUTLOOK_PAGE)
                     if has_tstm_img else img_fallback(TSTM_OUTLOOK_PAGE, "Thunderstorm Outlook"))

    # MDs
    if mds:
        md_rows = "".join(f"""
        <tr style="border-bottom:1px solid #f0e8c8;">
          <td style="padding:8px 12px;font-size:13px;color:#7a5200;font-weight:700;">#{m['num']}</td>
          <td style="padding:8px 12px;font-size:13px;">
            <a href="{m['url']}" style="color:#1a3a5c;text-decoration:none;">
              Mesoscale Discussion #{m['num']}
            </a>
          </td>
        </tr>""" for m in mds)
        md_html = f"""
        <table style="width:100%;border-collapse:collapse;background:#fffdf2;
                      border-radius:6px;overflow:hidden;border:1px solid #f0e8c8;">
          <tr style="background:#fff3cd;">
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#7a5200;
                       font-weight:700;text-transform:uppercase;width:70px;">MD #</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#7a5200;
                       font-weight:700;text-transform:uppercase;">Link</th>
          </tr>{md_rows}
        </table>"""
    else:
        md_html = "<p style='color:#888;font-style:italic;font-size:13px;margin:0;'>No active mesoscale discussions at time of send.</p>"

    btns = "".join(
        f'<a href="{url}" style="display:inline-block;margin:4px 5px 4px 0;padding:7px 13px;'
        f'background:#1a1f5e;color:#d4a843;border-radius:5px;font-size:12px;'
        f'font-weight:700;text-decoration:none;">{name}</a>'
        for name, url in [
            ("Day 1 Outlook", OUTLOOK_PAGES[1]),
            ("Day 2 Outlook", OUTLOOK_PAGES[2]),
            ("Day 3 Outlook", OUTLOOK_PAGES[3]),
            ("Active MDs",    f"{SPC_BASE}/products/md/"),
            ("SPC Homepage",  SPC_BASE),
        ]
    )

    def card(title, content, border="#1a1f5e"):
        return f"""
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;
              padding:20px 22px;border-top:4px solid {border};">
    <h2 style="margin:0 0 14px;font-size:14px;color:#1a1f5e;text-transform:uppercase;
               letter-spacing:0.8px;font-weight:700;">{title}</h2>
    {content}
  </div>"""

    def pre(text, border_color, bg):
        return (f'<pre style="background:{bg};border-left:3px solid {border_color};'
                f'padding:10px 14px;font-size:12px;white-space:pre-wrap;'
                f'border-radius:0 4px 4px 0;margin:0;color:#333;'
                f'line-height:1.6;font-family:monospace;">{text}</pre>')

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eef0f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:680px;margin:0 auto;">

  <!-- HEADER -->
  <div style="background:#1a1f5e;padding:28px 28px 22px;text-align:center;">
    <img src="cid:cwo_logo" alt="Colletti Weather Office"
         style="max-width:130px;height:auto;display:block;margin:0 auto 14px;" />
    <h1 style="margin:0;color:#d4a843;font-size:20px;letter-spacing:1.5px;
               text-transform:uppercase;font-weight:700;">Daily SPC Outlook Brief</h1>
    <p style="margin:6px 0 2px;color:#8fa8d8;font-size:13px;">
      NWS Chicago (LOT) &nbsp;&middot;&nbsp; NWS Milwaukee (MKX) &nbsp;&middot;&nbsp; NWS Quad Cities (DVN)
    </p>
    <p style="margin:0;color:#5566aa;font-size:11px;">{now_utc}</p>
  </div>

  {card("&#128202; National Categorical Risk", f"""
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;width:120px;">Day 1 Outlook</td>
        <td style="padding:10px 14px;font-size:14px;">{nat1}</td>
        <td style="padding:6px 14px;text-align:right;"><a href="{OUTLOOK_PAGES[1]}" style="font-size:11px;color:#1a3a5c;text-decoration:none;">View &#8599;</a></td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 2 Outlook</td>
        <td style="padding:10px 14px;font-size:14px;">{nat2}</td>
        <td style="padding:6px 14px;text-align:right;"><a href="{OUTLOOK_PAGES[2]}" style="font-size:11px;color:#1a3a5c;text-decoration:none;">View &#8599;</a></td>
      </tr>
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 3 Outlook</td>
        <td style="padding:10px 14px;font-size:14px;">{nat3}</td>
        <td style="padding:6px 14px;text-align:right;"><a href="{OUTLOOK_PAGES[3]}" style="font-size:11px;color:#1a3a5c;text-decoration:none;">View &#8599;</a></td>
      </tr>
    </table>""")}

  {card("&#128205; CWO Area Risk (LOT / MKX / DVN)", f"""
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:13px;width:120px;">Categorical</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['cat']}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#c0392b;font-size:13px;">&#127754; Tornado</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['torn']}</td>
      </tr>
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#2471a3;font-size:13px;">&#128168; Wind</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['wind']}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#1e8449;font-size:13px;">&#129514; Hail</td>
        <td style="padding:10px 14px;font-size:13px;">{cwo_risks['hail']}</td>
      </tr>
    </table>
    <p style="font-size:11px;color:#bbb;margin:10px 0 0;">Based on SPC probability contours intersecting LOT/MKX/DVN bounding box.</p>""",
    border="#d4a843")}

  {card("&#128506; Day 1 Convective Outlook Map", conv_img_html)}

  {card("&#9928; Thunderstorm Outlook", tstm_img_html)}

  {card("&#9889; Day 1 Hazard Text", f"""
    <p style="font-weight:700;color:#c0392b;font-size:13px;margin:0 0 4px;">&#127754; TORNADO</p>
    {pre(torn_txt, '#c0392b', '#fdf2f0')}
    <p style="font-weight:700;color:#2471a3;font-size:13px;margin:14px 0 4px;">&#128168; WIND</p>
    {pre(wind_txt, '#2471a3', '#eaf4fb')}
    <p style="font-weight:700;color:#1e8449;font-size:13px;margin:14px 0 4px;">&#129514; HAIL</p>
    {pre(hail_txt, '#1e8449', '#eafaf1')}
    <p style="font-weight:700;color:#6c3483;font-size:13px;margin:14px 0 4px;">&#9928; THUNDERSTORMS</p>
    {pre(tstm_txt, '#6c3483', '#f5eef8')}""")}

  {card("&#128203; Day 1 Outlook Full Text", f"""
    <pre style="background:#f4f6f8;padding:14px;font-size:12px;white-space:pre-wrap;
                border-radius:6px;margin:0;color:#222;line-height:1.65;font-family:monospace;">{summary}</pre>
    <p style="font-size:12px;color:#888;margin:8px 0 0;">
      Full product: <a href="{OUTLOOK_PAGES[1]}" style="color:#1a3a5c;">SPC Day 1 Outlook &#8599;</a>
    </p>""")}

  {card("&#128269; Active Mesoscale Discussions", f"""
    {md_html}
    <p style="font-size:12px;color:#888;margin:10px 0 0;">
      <a href="{SPC_BASE}/products/md/" style="color:#1a3a5c;">All active MDs on SPC &#8599;</a>
    </p>""")}

  {card("&#128279; SPC Links", btns)}

  <!-- FOOTER -->
  <div style="background:#1a1f5e;margin:14px 14px 0;border-radius:8px;
              padding:22px 24px;text-align:center;">
    <p style="margin:0 0 4px;color:#d4a843;font-weight:700;font-size:15px;letter-spacing:0.5px;">
      Colletti Weather Office
    </p>
    <p style="margin:0 0 4px;color:#8fa8d8;font-size:12px;">
      <a href="mailto:{REPLY_TO}" style="color:#aac4ee;">{REPLY_TO}</a>
    </p>
    <p style="margin:0 0 14px;">
      <a href="{YT_URL}" style="color:#d4a843;font-size:13px;font-weight:700;text-decoration:none;">
        &#9654; YouTube.com/@MidwestMeteorology
      </a>
    </p>
    <hr style="border:none;border-top:1px solid #2a3270;margin:12px 0;" />
    <p style="margin:0;color:#5566aa;font-size:11px;line-height:1.8;">
      You are subscribed to CWO weather alerts.<br>
      Per federal law (CAN-SPAM Act), you may unsubscribe at any time.<br>
      <a href="{UNSUB_URL}" style="color:#aac4ee;">Click here to unsubscribe</a>
    </p>
    <p style="margin:8px 0 0;color:#3a4488;font-size:10px;">
      Automated digest -- always verify with official NWS/SPC products.
    </p>
  </div>
  <div style="height:18px;"></div>

</div>
</body></html>"""


# -- SEND -----------------------------------------------------------------------

def send_email(subject, html_body, conv_img=None, tstm_img=None):
    msg = MIMEMultipart("related")
    msg["Subject"]  = subject
    msg["From"]     = GMAIL_USER
    msg["To"]       = TO_EMAIL
    msg["Reply-To"] = REPLY_TO

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # CWO logo
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cwo_logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo = MIMEImage(f.read())
        logo.add_header("Content-ID", "<cwo_logo>")
        logo.add_header("Content-Disposition", "inline", filename="cwo_logo.png")
        msg.attach(logo)
        print("[CWO] Logo attached.")
    else:
        print(f"[CWO] WARNING: cwo_logo.png not found at {logo_path}")

    # Convective outlook image
    if conv_img:
        img = MIMEImage(conv_img, _subtype="gif")
        img.add_header("Content-ID", "<conv_img>")
        img.add_header("Content-Disposition", "inline", filename="day1outlook.gif")
        msg.attach(img)
        print("[CWO] Convective outlook image attached.")

    # Thunderstorm outlook image
    if tstm_img:
        img2 = MIMEImage(tstm_img, _subtype="gif")
        img2.add_header("Content-ID", "<tstm_img>")
        img2.add_header("Content-Disposition", "inline", filename="thunderstorm_outlook.gif")
        msg.attach(img2)
        print("[CWO] Thunderstorm outlook image attached.")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"[CWO] Email sent to {TO_EMAIL}")


# -- MAIN -----------------------------------------------------------------------

def main():
    print("[CWO] Fetching outlook texts...")
    day1_text = get_outlook_text(1)
    day2_text = get_outlook_text(2)
    day3_text = get_outlook_text(3)
    print(f"[CWO] Day 1: {get_national_category(day1_text)}")

    print("[CWO] Querying CWO area risks...")
    cwo_risks = get_cwo_risks()
    print(f"[CWO] CWO: {cwo_risks['cat']}")

    print("[CWO] Fetching MDs...")
    mds = get_active_mds()
    print(f"[CWO] {len(mds)} active MD(s)")

    print("[CWO] Fetching convective outlook image...")
    conv_img = fetch_convective_outlook_image()

    print("[CWO] Fetching thunderstorm outlook image...")
    tstm_img = fetch_thunderstorm_image()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nat1    = get_national_category(day1_text)
    subject = f"[CWO] SPC Brief -- {now_str} | Day 1: {nat1} | CWO: {cwo_risks['cat']}"

    html = build_html(day1_text, day2_text, day3_text, cwo_risks, mds,
                      conv_img is not None, tstm_img is not None)
    send_email(subject, html, conv_img, tstm_img)
    print("[CWO] Done.")


if __name__ == "__main__":
    main()
