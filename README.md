# CWO SPC Daily Outlook Emailer
### Colletti Weather Office — LOT / MKX / DVN

Automatically emails a formatted SPC outlook brief every morning and afternoon covering Days 1–3 categorical risk, tornado/wind/hail probabilities, active Mesoscale Discussions, and direct links to all SPC graphics.

---

##  LEGAL & PROPRIETARY NOTICE
**Copyright (c) 2026 Jonathan Colletti. All Rights Reserved.**

This repository and its source code are the exclusive property of **Jonathan Colletti**. The **Colletti Weather Office** (owned and operated by Jonathan Colletti) has the exclusive right to use, modify, and broadcast this software.

**NOT FOR PUBLIC USE:** 
While this repository is publicly viewable for educational and review purposes, **no license is granted** to any third party to download, copy, modify, distribute, or execute this code for personal, commercial, or broadcast use. Unauthorized use is a violation of international copyright law.

---

## SYSTEM OVERVIEW
This system is an automated alerting tool designed specifically for the **Colletti Weather Office** YouTube media channels. It utilizes Python and GitHub Actions to parse SPC data and distribute formatted briefs.

### Key Features:
- **Day 1–3 Risk Assessment:** Categorical risk levels with emoji indicators.
- **Severe Probabilities:** Automated extraction of tornado, wind, and hail threats.
- **Regional Focus:** Flagged Mesoscale Discussions for NWS Chicago (LOT), Milwaukee (MKX), and Quad Cities (DVN).
- **Scheduled Delivery:** 8:00 AM and 2:00 PM CDT automated updates.

---

## FILES
```text
CWO-SPC-AutoEmail/
├── .github/
│   └── workflows/
│       └── spc_emailer.yml    # GitHub Actions automation schedule
├── spc_emailer.py             # Main Python script for SPC data & emails
├── LICENSE                    # Proprietary license (Jonathan Colletti)
└── CODEOWNERS                 # Ownership & review authority file

