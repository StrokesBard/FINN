"""Spike 5: ticker mapping + management-change bios.

  a) NSE master list (EQUITY_L.csv), symbol-change and name-change files
  b) name -> symbol fuzzy lookup for user search
  c) BSE scrip code <-> NSE symbol via ISIN (from the BSE bhavcopy)
  d) management-change filings: does the filing itself carry the appointee's profile?
  e) LinkedIn: robots check only
"""
import difflib
import io
import re
from datetime import date, timedelta

import pandas as pd
import pdfplumber

from _common import get, robots_verdict

print("a) NSE master files")
r = get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
eq = pd.read_csv(io.BytesIO(r.content))
eq.columns = [c.strip() for c in eq.columns]
print(f"   EQUITY_L: {len(eq):,} rows, columns {list(eq.columns)}")
print(f"   series: {eq['SERIES'].value_counts().to_dict()}")
for name in ("symchange.csv", "namechange.csv"):
    r = get(f"https://nsearchives.nseindia.com/content/equities/{name}")
    if r is not None and r.status_code == 200:
        df = pd.read_csv(io.BytesIO(r.content), encoding="latin-1", header=None)
        print(f"   {name}: {len(df):,} rows; last 3:\n{df.tail(3).to_string(index=False, header=False)}")

print("\nb) name -> symbol lookup")
names = dict(zip(eq["NAME OF COMPANY"].str.upper(), eq["SYMBOL"]))
for q in ["Infosys", "HDFC Bank", "Tata Motors", "Indian Railway Catering", "reliance"]:
    hits = [n for n in names if q.upper() in n][:4] or difflib.get_close_matches(q.upper(), names, n=3)
    print(f"   {q!r:28} -> {[(h, names[h]) for h in hits]}")

print("\nc) BSE scrip code via ISIN")
d = date.today()
for _ in range(6):
    d -= timedelta(days=1)
    r = get(f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV")
    if r is not None and r.status_code == 200 and b"TradDt" in r.content[:300]:
        bse = pd.read_csv(io.BytesIO(r.content))
        m = eq.merge(bse[["ISIN", "FinInstrmId", "TckrSymb"]], left_on="ISIN NUMBER", right_on="ISIN", how="left")
        print(f"   NSE EQ symbols with a BSE code via ISIN: {m['FinInstrmId'].notna().sum():,} / {len(eq):,}")
        print(f"   NSE-only (no BSE match): {m[m['FinInstrmId'].isna()]['SYMBOL'].head(5).tolist()} ...")
        break

print("\nd) management-change filings (last 10 days, all companies)")
to, frm = date.today(), date.today() - timedelta(days=10)
r = get(f"https://www.nseindia.com/api/corporate-announcements?index=equities"
        f"&from_date={frm:%d-%m-%Y}&to_date={to:%d-%m-%Y}", timeout=60)
items = r.json() if r is not None and r.status_code == 200 else []
mc = [a for a in items if re.search(r"change in director|appointment|cessation|resignation", a["desc"], re.I)]
print(f"   {len(mc)} management-change-like filings out of {len(items):,}")
appoint = [a for a in mc if re.search(r"appoint", (a.get("attchmntText") or "") + a["desc"], re.I)
           and a["attchmntFile"].lower().endswith(".pdf")]
found = 0
for a in appoint[:8]:
    p = get(a["attchmntFile"], timeout=60)
    if p is None or p.status_code != 200 or p.content[:4] != b"%PDF":
        continue
    with pdfplumber.open(io.BytesIO(p.content)) as pdf:
        text = " ".join((pg.extract_text() or "") for pg in pdf.pages[:6])
    flat = " ".join(text.split())
    m = re.search(r"(brief profile|profile of|experience|qualification)", flat, re.I)
    found += bool(m)
    print(f"   - {a['symbol']:<12} {a['desc'][:45]:<45} chars={len(flat):>6} profile={'yes' if m else 'no'}")
    if m:
        print("       ...", flat[max(0, m.start() - 60):m.start() + 260], "...")
print(f"   filings with a profile section: {found}/{min(len(appoint), 8)}")
xbrl_mc = [a for a in mc if "xbrl" in a["desc"].lower() or a["attchmntFile"].lower().endswith(".xml")]
print(f"   management-change filings that are XBRL: {len(xbrl_mc)}")
if xbrl_mc:
    x = get(xbrl_mc[0]["attchmntFile"])
    if x is not None and x.status_code == 200:
        tags = sorted(set(re.findall(rb"<[\w\-]+:([A-Za-z]+)[ >]", x.content)))
        print("   XBRL tags sample:", [t.decode() for t in tags if re.search(rb"Name|Designation|Reason|Date|Profile|Experience", t)][:25])

print("\ne) LinkedIn")
ok, note = robots_verdict("https://www.linkedin.com/in/some-person/")
print(f"   robots allowed={ok} ({note})")
