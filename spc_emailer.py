"""
CWO SPC Daily Outlook Emailer v3
Colletti Weather Office - LOT / MKX / DVN
"""

import smtplib
import urllib.request
import urllib.error
import json
import re
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
GMAIL_USER  = os.environ["GMAIL_USER"]
GMAIL_PASS  = os.environ["GMAIL_PASS"]
TO_EMAIL    = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO    = "collettiweather@gmail.com"
UNSUB_URL   = "https://forms.gle/Jg5opiANhsZfBGYT9"
YT_URL      = "https://www.youtube.com/@MidwestMeteorology"

SPC_BASE    = "https://www.spc.noaa.gov"

# Raw text product URLs (tgftp - always available, no auth needed)
TEXT_URLS = {
    1: "https://tgftp.nws.noaa.gov/data/raw/ac/acus01.kwns.swo.dy1.txt",
    2: "https://tgftp.nws.noaa.gov/data/raw/ac/acus02.kwns.swo.dy2.txt",
    3: "https://tgftp.nws.noaa.gov/data/raw/ac/acus03.kwns.swo.dy3.txt",
}

# SPC outlook page links (for clickable links in email — open in browser)
OUTLOOK_PAGE_URLS = {
    1: f"{SPC_BASE}/products/outlook/day1otlk.html",
    2: f"{SPC_BASE}/products/outlook/day2otlk.html",
    3: f"{SPC_BASE}/products/outlook/day3otlk.html",
}

# SPC graphic URLs — these open on spc.noaa.gov in the browser
GRAPHIC_LINKS = {
    "Day 1 Categorical":  f"{SPC_BASE}/products/outlook/day1otlk.html",
    "Day 1 Tornado Prob": f"{SPC_BASE}/products/outlook/day1probotlk.html#torn",
    "Day 1 Wind Prob":    f"{SPC_BASE}/products/outlook/day1probotlk.html#wind",
    "Day 1 Hail Prob":    f"{SPC_BASE}/products/outlook/day1probotlk.html#hail",
    "Day 2 Outlook":      f"{SPC_BASE}/products/outlook/day2otlk.html",
    "Day 3 Outlook":      f"{SPC_BASE}/products/outlook/day3otlk.html",
    "All SPC Outlooks":   f"{SPC_BASE}/products/outlook/",
    "Active MDs":         f"{SPC_BASE}/products/md/",
    "SPC Homepage":       f"{SPC_BASE}/",
}

# NWS API for active MDs (official, always works)
NWS_PRODUCTS_URL = "https://api.weather.gov/products/types/MCD/locations/KWNS?limit=10"
# ───────────────────────────────────────────────────────────────────────────────


def fetch(url, timeout=20):
    headers = {
        "User-Agent": "CWO-SPC-Emailer/3.0 (collettiweather@gmail.com)",
        "Accept": "text/plain, text/html, application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url):
    headers = {
        "User-Agent": "CWO-SPC-Emailer/3.0 (collettiweather@gmail.com)",
        "Accept": "application/geo+json, application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def get_outlook_text(day=1):
    """Fetch raw SPC text product from tgftp."""
    url = TEXT_URLS.get(day)
    if not url:
        return f"[No URL configured for Day {day}]"
    try:
        raw = fetch(url)
        # Strip header lines up to the actual product body
        lines = raw.splitlines()
        body_lines = []
        in_body = False
        for line in lines:
            stripped = line.strip()
            # Body starts after the SWODY line
            if re.match(r"SWODY\d", stripped):
                in_body = True
                continue
            if in_body:
                body_lines.append(line)
        text = "\n".join(body_lines).strip()
        # Cut off at $$
        text = re.sub(r"\$\$.*", "", text, flags=re.DOTALL).strip()
        return text if text else raw[:3000]
    except Exception as e:
        return f"[Could not retrieve Day {day} outlook: {e}]"


RISK_ORDER = [
    ("PARTICULARLY DANGEROUS SITUATION", "🔴 PDS — Particularly Dangerous Situation"),
    ("HIGH RISK",     "🔴 HIGH RISK"),
    ("MODERATE RISK", "🟠 MODERATE RISK"),
    ("ENHANCED RISK", "🟡 ENHANCED RISK"),
    ("SLIGHT RISK",   "🟡 SLIGHT RISK"),
    ("MARGINAL RISK", "🟢 MARGINAL RISK"),
    ("THUNDERSTORMS", "⚪ GENERAL THUNDERSTORMS"),
]


def get_outlook_category(day=1):
    text = get_outlook_text(day)
    upper = text.upper()
    for keyword, label in RISK_ORDER:
        if keyword in upper:
            return label, text
    return "⚪ NO THUNDER / BELOW THRESHOLD", text


def get_active_mds():
    """Fetch active MDs via NWS API."""
    results = []
    try:
        data = fetch_json(NWS_PRODUCTS_URL)
        products = data.get("@graph", [])
        for p in products[:8]:
            pid  = p.get("id", "")
            num  = re.search(r"MCD\s*(\d+)", p.get("productName", ""), re.IGNORECASE)
            num  = num.group(1) if num else pid[-4:] if pid else "???"
            url  = f"{SPC_BASE}/products/md/md{num.zfill(4)}.html"
            results.append({
                "num":   num,
                "title": p.get("productName", f"Mesoscale Discussion #{num}"),
                "url":   url,
                "time":  p.get("issuanceTime", ""),
            })
    except Exception as e:
        print(f"[CWO] NWS API MD fetch failed: {e} — falling back to SPC page scrape")
        try:
            html = fetch(f"{SPC_BASE}/products/md/")
            links = re.findall(r'href="[./]*/products/md/(md\d+\.html)"', html)
            seen = set()
            for link in links[:8]:
                num_m = re.search(r"md(\d+)\.html", link)
                num   = num_m.group(1).lstrip("0") or "0" if num_m else "???"
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


def extract_section(text, keyword):
    """Pull a named hazard section from the outlook text."""
    pattern = rf"\.\.\.{keyword}\.\.\..*?(?=\.\.\.[A-Z]{{3,}}\.\.\.|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if m:
        s = m.group(0).strip()
        return (s[:700] + "...") if len(s) > 700 else s
    return f"No specific {keyword.lower()} section found."


def build_html(day1_cat, day1_text, day2_cat, day3_cat, mds):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    torn = extract_section(day1_text, "TORNADO")
    wind = extract_section(day1_text, "WIND")
    hail = extract_section(day1_text, "HAIL")
    summary = day1_text[:1400].strip()

    # ── MD section ──
    if mds:
        md_rows = ""
        for m in mds:
            t = m["time"][:10] if m["time"] else ""
            md_rows += f"""
            <tr>
              <td style="padding:8px 12px;font-size:13px;color:#1a1f5e;font-weight:600;">#{m['num']}</td>
              <td style="padding:8px 12px;font-size:13px;">
                <a href="{m['url']}" style="color:#1a3a5c;text-decoration:none;">{m['title']}</a>
              </td>
              <td style="padding:8px 12px;font-size:12px;color:#888;">{t}</td>
            </tr>"""
        md_html = f"""
        <table style="width:100%;border-collapse:collapse;background:#fffdf0;border-radius:6px;overflow:hidden;">
          <tr style="background:#fff3cd;">
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#7a5200;font-weight:700;">MD #</th>
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#7a5200;font-weight:700;">Title</th>
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#7a5200;font-weight:700;">Issued</th>
          </tr>
          {md_rows}
        </table>"""
    else:
        md_html = "<p style='color:#666;font-style:italic;font-size:14px;margin:0;'>No active mesoscale discussions.</p>"

    # ── Graphic link buttons ──
    btns = ""
    for name, url in GRAPHIC_LINKS.items():
        btns += f'<a href="{url}" style="display:inline-block;margin:4px 5px 4px 0;padding:7px 13px;background:#1a1f5e;color:#d4a843;border-radius:5px;font-size:12px;font-weight:700;text-decoration:none;letter-spacing:0.3px;">{name}</a>'

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eef0f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:680px;margin:0 auto;">

  <!-- HEADER -->
  <div style="background:#1a1f5e;padding:28px 28px 22px;text-align:center;border-radius:0 0 0 0;">
    <img src="cid:cwo_logo" alt="CWO" style="max-width:130px;height:auto;margin-bottom:14px;display:block;margin-left:auto;margin-right:auto;" />
    <h1 style="margin:0;color:#d4a843;font-size:21px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;">
      Daily SPC Outlook Brief
    </h1>
    <p style="margin:6px 0 2px;color:#8fa8d8;font-size:13px;">
      NWS Chicago (LOT) &nbsp;·&nbsp; NWS Milwaukee (MKX) &nbsp;·&nbsp; NWS Quad Cities (DVN)
    </p>
    <p style="margin:0;color:#5566aa;font-size:11px;">{now_utc}</p>
  </div>

  <!-- CATEGORICAL RISK -->
  <div style="background:#fff;margin:14px 14px 0;border-radius:8px;padding:20px 22px;border-top:4px solid #1a1f5e;">
    <h2 style="margin:0 0 14px;font-size:15px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.6px;font-weight:700;">📊 Categorical Risk Summary</h2>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;width:80px;">Day 1</td>
        <td style="padding:10px 14px;font-size:14px;">{day1_cat}</td>
        <td style="padding:10px 14px;text-align:right;"><a href="{OUTLOOK_PAGE_URLS[1]}" style="font-size:11px;color:#1a3a5c;">View →</a></td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 2</td>
        <td style="padding:10px 14px;font-size:14px;">{day2_cat}</td>
        <td style="padding:10px 14px;text-align:right;"><a href="{OUTLOOK_PAGE_URLS[2]}" style="font-size:11px;color:#1a3a5c;">View →</a></td>
      </tr>
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 3</td>
        <td style="padding:10px 14px;font-size:14px;">{day3_cat}</td>
        <td style="padding:10px 14px;text-align:right;"><a href="{OUTLOOK_PAGE_URLS[3]}" style="font-size:11px;color:#1a3a5c;">View →</a></td>
      </tr>
    </table>
  </div>

  <!-- HAZARD PROBS -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 14px;font-size:15px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.6px;font-weight:700;">⚡ Day 1 Hazard Probabilities</h2>

    <p style="font-weight:700;color:#c0392b;font-size:13px;margin:0 0 4px;">🌪️ TORNADO</p>
    <pre style="background:#fdf2f0;border-left:3px solid #c0392b;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;color:#333;line-height:1.6;font-family:monospace;">{torn}</pre>

    <p style="font-weight:700;color:#2471a3;font-size:13px;margin:0 0 4px;">💨 WIND</p>
    <pre style="background:#eaf4fb;border-left:3px solid #2471a3;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;color:#333;line-height:1.6;font-family:monospace;">{wind}</pre>

    <p style="font-weight:700;color:#1e8449;font-size:13px;margin:0 0 4px;">🧊 HAIL</p>
    <pre style="background:#eafaf1;border-left:3px solid #1e8449;padding:10px 14px;font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0;color:#333;line-height:1.6;font-family:monospace;">{hail}</pre>
  </div>

  <!-- FULL SUMMARY -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 12px;font-size:15px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.6px;font-weight:700;">📋 Day 1 Full Text</h2>
    <pre style="background:#f4f6f8;padding:14px;font-size:12px;white-space:pre-wrap;border-radius:6px;margin:0;color:#222;line-height:1.65;font-family:monospace;">{summary}</pre>
    <p style="font-size:12px;color:#888;margin:8px 0 0;">
      Full product: <a href="{OUTLOOK_PAGE_URLS[1]}" style="color:#1a3a5c;">SPC Day 1 Outlook ↗</a>
    </p>
  </div>

  <!-- MDs -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 12px;font-size:15px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.6px;font-weight:700;">🔍 Active Mesoscale Discussions</h2>
    {md_html}
    <p style="font-size:12px;color:#888;margin:10px 0 0;">
      All active MDs: <a href="{SPC_BASE}/products/md/" style="color:#1a3a5c;">SPC Mesoscale Discussions ↗</a>
    </p>
  </div>

  <!-- GRAPHICS -->
  <div style="background:#fff;margin:10px 14px 0;border-radius:8px;padding:20px 22px;">
    <h2 style="margin:0 0 10px;font-size:15px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.6px;font-weight:700;">🗺️ SPC Links &amp; Graphics</h2>
    <p style="font-size:13px;color:#555;margin:0 0 12px;">Click to open each product on SPC:</p>
    {btns}
  </div>

  <!-- FOOTER -->
  <div style="background:#1a1f5e;margin:14px 14px 0;border-radius:8px;padding:22px 24px;text-align:center;">
    <p style="margin:0 0 4px;color:#d4a843;font-weight:700;font-size:15px;letter-spacing:0.5px;">
      Colletti Weather Office
    </p>
    <p style="margin:0 0 2px;color:#8fa8d8;font-size:12px;">
      @MidwestMeteorology &nbsp;|&nbsp;
      <a href="mailto:{REPLY_TO}" style="color:#aac4ee;">{REPLY_TO}</a>
    </p>
    <p style="margin:0 0 14px;">
      <a href="{YT_URL}" style="color:#d4a843;font-size:12px;text-decoration:none;font-weight:600;">
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
  <div style="height:18px;background:#eef0f5;"></div>

</div>
</body></html>"""


def send_email(subject, html_body):
    msg = MIMEMultipart("related")
    msg["Subject"]  = subject
    msg["From"]     = GMAIL_USER
    msg["To"]       = TO_EMAIL
    msg["Reply-To"] = REPLY_TO

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # Attach logo — look for it next to the script
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cwo_logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            img = MIMEImage(f.read())
        img.add_header("Content-ID", "<cwo_logo>")
        img.add_header("Content-Disposition", "inline", filename="cwo_logo.png")
        msg.attach(img)
        print("[CWO] Logo attached.")
    else:
        print(f"[CWO] Warning: logo not found at {logo_path} — email will send without it.")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"[CWO] Email sent to {TO_EMAIL}")


def main():
    print("[CWO] Fetching outlooks...")
    day1_cat, day1_text = get_outlook_category(1)
    day2_cat, _         = get_outlook_category(2)
    day3_cat, _         = get_outlook_category(3)
    print(f"[CWO] Day 1: {day1_cat}")
    print(f"[CWO] Day 2: {day2_cat}")
    print(f"[CWO] Day 3: {day3_cat}")

    print("[CWO] Fetching MDs...")
    mds = get_active_mds()
    print(f"[CWO] Found {len(mds)} MD(s)")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[CWO] SPC Brief — {now_str} | Day 1: {day1_cat}"

    html = build_html(day1_cat, day1_text, day2_cat, day3_cat, mds)
    send_email(subject, html)
    print("[CWO] Done.")


if __name__ == "__main__":
    main()
