"""Spike 6: cross-cutting checks the other spikes raised.

  a) NSE JSON API stability: 12 back-to-back calls, any 401/403/429?
  b) corporate actions (splits/bonus) for adjusting raw bhavcopy prices
  c) PDF text-extraction speed, pypdf vs pdfplumber (drives on-demand latency)
"""
import io
import time
from collections import Counter

import pdfplumber
import pypdf

from _common import get

print("a) NSE API stability")
codes = Counter()
syms = ["INFY", "TCS", "SBIN", "ITC", "LT", "MARUTI", "SUNPHARMA", "TITAN", "ASIANPAINT", "NTPC", "ONGC", "WIPRO"]
for s in syms:
    r = get(f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={s}"
            "&from_date=01-10-2026&to_date=03-11-2026")
    codes[r.status_code if r is not None else "ERR"] += 1
print("   status codes:", dict(codes))

print("\nb) corporate actions")
for s in ["HDFCBANK", "INFY"]:
    r = get(f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={s}")
    if r is not None and r.status_code == 200:
        rows = r.json()
        print(f"   {s}: {len(rows)} actions; keys {sorted(rows[0].keys()) if rows else None}")
        for x in [x for x in rows if any(k in x.get("subject", "").lower() for k in ("bonus", "split"))][:3]:
            print(f"     {x.get('exDate')} | {x.get('subject')}")

print("\nc) PDF extraction speed")
docs = {
    "transcript 17p": "https://nsearchives.nseindia.com/corporate/HDFCBANK_23102026224657_SEintimationTranscriptofearningscall17oct2026.pdf",
    "annual report 384p": "https://nsearchives.nseindia.com/annual_reports/AR_29313_INFY_2025_2026_U_8985411_30052026200413.pdf",
}
for label, u in docs.items():
    r = get(u, timeout=120)
    blob = r.content
    t = time.time()
    reader = pypdf.PdfReader(io.BytesIO(blob))
    txt = "".join((p.extract_text() or "") for p in reader.pages)
    t_pypdf = time.time() - t
    t = time.time()
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        n = min(len(pdf.pages), 40)
        _ = "".join((pdf.pages[i].extract_text() or "") for i in range(n))
    t_plumb = (time.time() - t) / n * len(reader.pages)
    print(f"   {label}: pypdf {t_pypdf:.1f}s for all pages, {len(txt):,} chars (~{len(txt) // 4:,} tokens); "
          f"pdfplumber est. {t_plumb:.1f}s for all pages")
