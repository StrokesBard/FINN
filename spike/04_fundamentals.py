"""Spike 4: fundamentals for the pull side (annual reports + concall transcripts).

Candidates:
  a) screener.in company page -> document links (ARs, concalls) + standardised tables
  b) NSE annual-reports API
  c) NSE announcements filtered to concall transcripts
  d) Download one AR and one transcript; is the text extractable, how big?
"""
import io
import re
import sys

import pdfplumber
from lxml import html

from _common import get, robots_verdict

SYMBOLS = sys.argv[1:] or ["INFY", "HDFCBANK", "IRCTC"]
PAGE_SAMPLE = 8  # pages to text-extract per PDF


def pdf_probe(url, label):
    r = get(url, timeout=90)
    if r is None or r.status_code != 200:
        print(f"    {label}: download failed")
        return
    if r.content[:4] != b"%PDF":
        print(f"    {label}: not a PDF (starts {r.content[:40]!r}) ctype={r.headers.get('Content-Type')}")
        return
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        n = len(pdf.pages)
        sample = [pdf.pages[i] for i in range(0, n, max(1, n // PAGE_SAMPLE))][:PAGE_SAMPLE]
        chars = [len(p.extract_text() or "") for p in sample]
    verdict = "text" if sum(c > 200 for c in chars) >= len(chars) * 0.6 else "MOSTLY IMAGE (needs OCR)"
    print(f"    {label}: {len(r.content) / 1e6:.1f} MB, {n} pages, chars/page sample {chars} -> {verdict}")


for sym in SYMBOLS:
    print(f"\n=== {sym}")

    print(" a) screener.in")
    docs = {}
    for path in (f"/company/{sym}/consolidated/", f"/company/{sym}/"):
        u = "https://www.screener.in" + path
        ok, note = robots_verdict(u)
        print(f"   robots allowed={ok} ({note})")
        r = get(u)
        if r is None or r.status_code != 200:
            continue
        tree = html.fromstring(r.content)
        ar = [(a.text_content().strip(), a.get("href")) for a in tree.xpath("//div[contains(@class,'annual-reports')]//a")]
        concalls = []
        for li in tree.xpath("//div[contains(@class,'concalls')]//li"):
            when = " ".join(li.xpath(".//div[contains(@class,'ink-600')]/text()")).strip()
            for a in li.xpath(".//a"):
                concalls.append((when, a.text_content().strip(), a.get("href")))
        tables = tree.xpath("//section[@id]/@id")
        print(f"   {path}: {len(ar)} annual reports, {len(concalls)} concall links, sections={tables}")
        for t in ar[:3]:
            print("     AR:", t)
        kinds = {}
        for when, kind, href in concalls:
            kinds[kind] = kinds.get(kind, 0) + 1
        print("     concall link kinds:", kinds)
        for c in [c for c in concalls if c[1].lower().startswith("transcript")][:3]:
            print("     transcript:", c)
        hosts = {re.sub(r"https?://([^/]+)/.*", r"\1", h) for _, _, h in concalls + [(None, None, h) for _, h in ar] if h}
        print("     link hosts:", sorted(hosts))
        docs = {"ar": ar, "concalls": concalls}
        break

    print(" b) NSE annual-reports API")
    r = get(f"https://www.nseindia.com/api/annual-reports?index=equities&symbol={sym}")
    nse_ar = []
    if r is not None and r.status_code == 200:
        j = r.json()
        nse_ar = j.get("data", j) if isinstance(j, dict) else j
        print(f"   {len(nse_ar)} reports; first: {nse_ar[0] if nse_ar else None}")

    print(" c) NSE announcements -> concall transcripts")
    r = get(f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}")
    trans = []
    if r is not None and r.status_code == 200:
        for a in r.json():
            t = (a.get("attchmntText") or "").lower()
            if "transcript" in t and a["attchmntFile"].lower().endswith(".pdf"):
                trans.append(a)
        print(f"   {len(trans)} transcript filings; newest 6:")
        for a in trans[:6]:
            print(f"     {a['an_dt']} | {a['desc']} | {a['attchmntText'][:110]}")

    print(" d) PDF text extractability")
    if nse_ar:
        u = nse_ar[0].get("fileName") or nse_ar[0].get("file")
        if u:
            pdf_probe(u, f"NSE AR {nse_ar[0].get('toYr', '')}")
    if trans:
        pdf_probe(trans[0]["attchmntFile"], "NSE transcript")
    if docs.get("concalls"):
        t = next((c for c in docs["concalls"] if c[1].lower().startswith("transcript")), None)
        if t:
            pdf_probe(t[2], "screener transcript link")
