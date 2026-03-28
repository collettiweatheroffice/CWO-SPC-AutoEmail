"""
CWO SPC Daily Outlook Emailer v2
Colletti Weather Office - LOT / MKX / DVN Coverage Areas
"""

import smtplib
import urllib.request
import json
import re
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"
UNSUB_URL  = "https://forms.gle/Jg5opiANhsZfBGYT9"

# CWO coverage bounding box (LOT + MKX + DVN combined)
LAT_MIN, LAT_MAX = 40.5, 44.0
LON_MIN, LON_MAX = -91.5, -86.5

SPC_BASE    = "https://www.spc.noaa.gov"
MD_JSON_URL = "https://www.spc.noaa.gov/products/md/json/md_summary.json"

# CWO logo as base64 inline image
CWO_LOGO_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoH"
# ── END CONFIG ─────────────────────────────────────────────────────────────────


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "CWO-SPC-Emailer/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url):
    return json.loads(fetch(url))


def get_outlook_text(day=1):
    text_url = f"{SPC_BASE}/products/outlook/day{day}otlk_txt.html"
    try:
        raw = fetch(text_url)
        clean = re.sub(r"<[^>]+>", "", raw)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        match = re.search(r"(\.\.\..*?)(\$\$)", clean, re.DOTALL)
        return match.group(1).strip() if match else clean[:3000]
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
        ("THUNDERSTORMS","⚪ GENERAL THUNDERSTORMS"),
    ]
    upper = text.upper()
    for keyword, label in categories:
        if keyword in upper:
            return label, text
    return "⚪ NO THUNDER / BELOW THRESHOLD", text


def get_graphic_links():
    return {
        "Day 1 Categorical":  f"{SPC_BASE}/products/outlook/day1otlk.gif",
        "Day 1 Tornado Prob": f"{SPC_BASE}/products/outlook/day1probotlk_torn.gif",
        "Day 1 Wind Prob":    f"{SPC_BASE}/products/outlook/day1probotlk_wind.gif",
        "Day 1 Hail Prob":    f"{SPC_BASE}/products/outlook/day1probotlk_hail.gif",
        "Day 2 Categorical":  f"{SPC_BASE}/products/outlook/day2otlk.gif",
        "Day 2 Tornado Prob": f"{SPC_BASE}/products/outlook/day2probotlk_torn.gif",
        "Day 2 Wind Prob":    f"{SPC_BASE}/products/outlook/day2probotlk_wind.gif",
        "Day 2 Hail Prob":    f"{SPC_BASE}/products/outlook/day2probotlk_hail.gif",
        "Day 3 Outlook":      f"{SPC_BASE}/products/outlook/day3otlk.gif",
    }


def get_active_mds():
    try:
        data = fetch_json(MD_JSON_URL)
        mds = data.get("mds", [])
    except Exception:
        try:
            html = fetch(f"{SPC_BASE}/products/md/")
            md_links = re.findall(r'href="(/products/md/md\d+\.html)"', html)
            if not md_links:
                return []
            results = []
            for link in md_links[:5]:
                num_match = re.search(r'md(\d+)\.html', link)
                num = num_match.group(1).lstrip("0") if num_match else "???"
                results.append({
                    "num":      num,
                    "title":    f"Mesoscale Discussion #{num}",
                    "url":      f"{SPC_BASE}{link}",
                    "near_cwo": True,
                })
            return results
        except Exception:
            return []

    results = []
    for md in mds:
        try:
            lat1 = float(md.get("lat1", 0))
            lat2 = float(md.get("lat2", 0))
            lon1 = float(md.get("lon1", 0))
            lon2 = float(md.get("lon2", 0))
            if lon1 > 0: lon1 = -lon1
            if lon2 > 0: lon2 = -lon2
            lon_lo, lon_hi = min(lon1, lon2), max(lon1, lon2)
            lat_lo, lat_hi = min(lat1, lat2), max(lat1, lat2)
            overlaps = (lat_lo < LAT_MAX and lat_hi > LAT_MIN and
                        lon_lo < LON_MAX and lon_hi > LON_MIN)
        except Exception:
            overlaps = False

        results.append({
            "num":      md.get("mdnum", "???"),
            "title":    md.get("title", "Mesoscale Discussion"),
            "url":      f"{SPC_BASE}/products/md/md{str(md.get('mdnum','')).zfill(4)}.html",
            "near_cwo": overlaps,
        })
    return results


def extract_prob_text(outlook_text, hazard="TORNADO"):
    pattern = rf"\.\.\.{hazard}\.\.\..*?(?=\.\.\.[A-Z]{{3,}}\.\.\.|\Z)"
    match = re.search(pattern, outlook_text, re.DOTALL | re.IGNORECASE)
    if match:
        section = match.group(0).strip()
        return section[:600] + ("..." if len(section) > 600 else "")
    return f"No specific {hazard.lower()} section found in Day 1 outlook."


def build_email_html(day1_cat, day1_text, day2_cat, day3_cat, mds, graphics):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    torn_prob = extract_prob_text(day1_text, "TORNADO")
    wind_prob = extract_prob_text(day1_text, "WIND")
    hail_prob = extract_prob_text(day1_text, "HAIL")
    summary   = day1_text[:1200].strip()

    # Mesoscale discussions section
    md_section = ""
    if mds:
        near = [m for m in mds if m.get("near_cwo")]
        far  = [m for m in mds if not m.get("near_cwo")]
        if near:
            md_section += """
            <div style="background:#fff8e1;border-left:4px solid #f9a825;padding:12px 16px;border-radius:0 6px 6px 0;margin-bottom:12px;">
              <strong style="color:#e65100;font-size:14px;">⚠️ Active MDs — Near CWO Area (LOT/MKX/DVN)</strong>
              <ul style="margin:8px 0 0;padding-left:18px;">"""
            for m in near:
                md_section += f"<li style='margin:4px 0;'><a href='{m['url']}' style='color:#1a3a5c;font-weight:500;'>MD #{m['num']} — {m['title']}</a></li>"
            md_section += "</ul></div>"
        if far:
            md_section += "<p style='font-size:13px;color:#666;margin:8px 0 4px;font-weight:500;'>Outside CWO Area:</p><ul style='margin:0;padding-left:18px;color:#777;font-size:13px;'>"
            for m in far:
                md_section += f"<li style='margin:3px 0;'><a href='{m['url']}' style='color:#555;'>MD #{m['num']} — {m['title']}</a></li>"
            md_section += "</ul>"
    else:
        md_section = "<p style='color:#666;font-style:italic;font-size:14px;margin:0;'>No active mesoscale discussions at time of send.</p>"

    # Graphic link buttons
    graphic_buttons = ""
    for name, url in graphics.items():
        graphic_buttons += f"""
        <a href="{url}" style="display:inline-block;margin:4px 6px 4px 0;padding:7px 14px;
           background:#1a3a5c;color:#d4a843;border-radius:5px;font-size:12px;font-weight:600;
           text-decoration:none;letter-spacing:0.3px;">{name}</a>"""

    html = f"""
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:680px;margin:0 auto;background:#f0f2f5;">

  <!-- HEADER WITH LOGO -->
  <div style="background:#1a1f5e;padding:28px 28px 20px;text-align:center;">
    <img src="cid:cwo_logo" alt="Colletti Weather Office"
         style="max-width:140px;height:auto;margin-bottom:12px;" />
    <h1 style="margin:0;color:#d4a843;font-size:22px;letter-spacing:1.5px;text-transform:uppercase;">
      Daily SPC Outlook Brief
    </h1>
    <p style="margin:6px 0 0;color:#8899cc;font-size:13px;">
      NWS Chicago (LOT) &nbsp;·&nbsp; NWS Milwaukee (MKX) &nbsp;·&nbsp; NWS Quad Cities (DVN)
    </p>
    <p style="margin:4px 0 0;color:#6677aa;font-size:11px;">{now_utc}</p>
  </div>

  <!-- CATEGORICAL RISK SUMMARY -->
  <div style="background:#fff;margin:16px 16px 0;border-radius:8px;padding:20px 24px;
              border-top:4px solid #1a1f5e;">
    <h2 style="margin:0 0 14px;font-size:16px;color:#1a1f5e;text-transform:uppercase;
               letter-spacing:0.5px;">📊 Categorical Risk Summary</h2>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;border-radius:4px 0 0 4px;">Day 1</td>
        <td style="padding:10px 14px;font-size:14px;">{day1_cat}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;">Day 2</td>
        <td style="padding:10px 14px;font-size:14px;">{day2_cat}</td>
      </tr>
      <tr style="background:#eef1f8;">
        <td style="padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;border-radius:4px 0 0 4px;">Day 3</td>
        <td style="padding:10px 14px;font-size:14px;">{day3_cat}</td>
      </tr>
    </table>
  </div>

  <!-- HAZARD PROBABILITIES -->
  <div style="background:#fff;margin:12px 16px 0;border-radius:8px;padding:20px 24px;">
    <h2 style="margin:0 0 14px;font-size:16px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.5px;">
      ⚡ Day 1 Hazard Probabilities
    </h2>

    <p style="font-weight:700;color:#c0392b;font-size:13px;margin:0 0 4px;">🌪️ TORNADO</p>
    <pre style="background:#fdf2f0;border-left:3px solid #c0392b;padding:10px 14px;
                font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;
                color:#444;line-height:1.6;">{torn_prob}</pre>

    <p style="font-weight:700;color:#2471a3;font-size:13px;margin:0 0 4px;">💨 WIND</p>
    <pre style="background:#eaf4fb;border-left:3px solid #2471a3;padding:10px 14px;
                font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0 0 14px;
                color:#444;line-height:1.6;">{wind_prob}</pre>

    <p style="font-weight:700;color:#1e8449;font-size:13px;margin:0 0 4px;">🧊 HAIL</p>
    <pre style="background:#eafaf1;border-left:3px solid #1e8449;padding:10px 14px;
                font-size:12px;white-space:pre-wrap;border-radius:0 4px 4px 0;margin:0;
                color:#444;line-height:1.6;">{hail_prob}</pre>
  </div>

  <!-- OUTLOOK SUMMARY -->
  <div style="background:#fff;margin:12px 16px 0;border-radius:8px;padding:20px 24px;">
    <h2 style="margin:0 0 12px;font-size:16px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.5px;">
      📋 Day 1 Outlook Summary
    </h2>
    <pre style="background:#f4f6f8;padding:14px;font-size:12px;white-space:pre-wrap;
                border-radius:6px;margin:0;color:#333;line-height:1.6;">{summary}</pre>
    <p style="font-size:12px;color:#888;margin:8px 0 0;">
      Full product: <a href="{SPC_BASE}/products/outlook/day1otlk.html" style="color:#1a3a5c;">SPC Day 1 Outlook</a>
    </p>
  </div>

  <!-- MESOSCALE DISCUSSIONS -->
  <div style="background:#fff;margin:12px 16px 0;border-radius:8px;padding:20px 24px;">
    <h2 style="margin:0 0 12px;font-size:16px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.5px;">
      🔍 Mesoscale Discussions
    </h2>
    {md_section}
    <p style="font-size:12px;color:#888;margin:10px 0 0;">
      All active MDs: <a href="{SPC_BASE}/products/md/" style="color:#1a3a5c;">SPC Mesoscale Discussions</a>
    </p>
  </div>

  <!-- SPC GRAPHICS -->
  <div style="background:#fff;margin:12px 16px 0;border-radius:8px;padding:20px 24px;">
    <h2 style="margin:0 0 10px;font-size:16px;color:#1a1f5e;text-transform:uppercase;letter-spacing:0.5px;">
      🗺️ SPC Graphics
    </h2>
    <p style="font-size:13px;color:#555;margin:0 0 12px;">Click any graphic to open on SPC servers:</p>
    {graphic_buttons}
  </div>

  <!-- FOOTER -->
  <div style="background:#1a1f5e;margin:16px 16px 0;border-radius:8px 8px 0 0;
              padding:20px 24px;text-align:center;">
    <p style="margin:0 0 6px;color:#d4a843;font-weight:700;font-size:15px;letter-spacing:0.5px;">
      Colletti Weather Office
    </p>
    <p style="margin:0 0 4px;color:#8899cc;font-size:12px;">
      @MidwestMeteorology &nbsp;|&nbsp; <a href="mailto:{REPLY_TO}" style="color:#aabddd;">{REPLY_TO}</a>
    </p>
    <p style="margin:0 0 14px;color:#6677aa;font-size:11px;">
      NWS Chicago (LOT) · NWS Milwaukee (MKX) · NWS Quad Cities (DVN)
    </p>
    <hr style="border:none;border-top:1px solid #2a3070;margin:12px 0;" />
    <p style="margin:0;color:#6677aa;font-size:11px;line-height:1.7;">
      You are receiving this email because you subscribed to CWO weather alerts.<br>
      Per federal law (CAN-SPAM Act), you have the right to unsubscribe at any time.<br>
      <a href="{UNSUB_URL}" style="color:#aabddd;text-decoration:underline;">Click here to unsubscribe</a>
    </p>
    <p style="margin:8px 0 0;color:#4455aa;font-size:10px;">
      This is an automated digest. Always verify with official NWS/SPC products.
    </p>
  </div>
  <div style="height:16px;background:#f0f2f5;"></div>

</div>
</body></html>
"""
    return html


def send_email(subject, html_body, logo_path="/mnt/user-data/uploads/IMG_2462.PNG"):
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg["Reply-To"] = REPLY_TO

    # Attach HTML
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # Attach logo as inline image
    try:
        from email.mime.image import MIMEImage
        with open(logo_path, "rb") as f:
            img = MIMEImage(f.read())
        img.add_header("Content-ID", "<cwo_logo>")
        img.add_header("Content-Disposition", "inline", filename="cwo_logo.png")
        msg.attach(img)
    except Exception as e:
        print(f"[CWO] Warning: could not attach logo: {e}")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"[CWO] Email sent to {TO_EMAIL}")


def main():
    print("[CWO] Fetching SPC outlooks...")
    day1_cat, day1_text = get_outlook_category(1)
    day2_cat, _         = get_outlook_category(2)
    day3_cat, _         = get_outlook_category(3)

    print("[CWO] Fetching active MDs...")
    mds = get_active_mds()

    graphics = get_graphic_links()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[CWO] SPC Outlook Brief — {now_str} | Day 1: {day1_cat}"

    print("[CWO] Building email...")
    html = build_email_html(day1_cat, day1_text, day2_cat, day3_cat, mds, graphics)

    print("[CWO] Sending...")
    send_email(subject, html)
    print("[CWO] Done.")


if __name__ == "__main__":
    main()
