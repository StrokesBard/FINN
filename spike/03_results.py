"""Spike 3: quarterly results -> Revenue / EBITDA / PBT / PAT, QoQ and YoY.

Two NSE listings, split by date:
  - /api/corporates-financial-results   legacy XBRL, ends with the Dec-2024 quarter
  - /api/integrated-filing-results      "Integrated Filing- Financials", Mar-2025 onwards
Plus: can the results PDF itself be read as text?
"""
import io
import sys
from collections import defaultdict
from datetime import datetime

import pdfplumber
from lxml import etree

from _common import get

XBRLI = "{http://www.xbrl.org/2003/instance}"
SYMBOLS = sys.argv[1:] or ["INFY", "RELIANCE", "HDFCBANK", "BAJFINANCE", "IRCTC"]

# candidate element names, first hit wins. Banks use a different taxonomy.
NONBANK = {
    "revenue": ["RevenueFromOperations"],
    "other_income": ["OtherIncome"],
    "finance_costs": ["FinanceCosts"],
    "dep": ["DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"],
    "pbt": ["ProfitBeforeTax", "ProfitLossBeforeTax"],
    "pat": ["ProfitLossForPeriod", "ProfitLossForThePeriod"],
    "pat_owners": ["ProfitOrLossAttributableToOwnersOfParent"],
}
# NBFCs file Ind-AS Division III: InterestEarned + FinanceCosts, no EBITDA concept
NBFC = {
    "interest_earned": ["InterestEarned"],
    "finance_costs": ["FinanceCosts"],
    "impairment": ["ImpairmentOnFinancialInstruments"],
    "revenue": ["RevenueFromOperations"],
    "pbt": ["ProfitBeforeTax"],
    "pat": ["ProfitLossForPeriod"],
    "pat_owners": ["ProfitOrLossAttributableToOwnersOfParent"],
}
BANK = {
    "interest_earned": ["InterestEarned"],
    "interest_expended": ["InterestExpended"],
    "other_income": ["OtherIncome"],
    "ppop": ["OperatingProfitBeforeProvisionAndContingencies"],
    "provisions": ["ProvisionsOtherThanTaxAndContingencies"],
    "pbt": ["ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeTax"],
    "pat": ["ProfitLossForThePeriod", "ProfitLossForPeriod"],
    "gnpa_pct": ["PercentageOfGrossNpa"],
}


def parse_xbrl(blob):
    root = etree.fromstring(blob)
    ctx = {}
    for c in root.iter(XBRLI + "context"):
        if c.find(".//{http://xbrl.org/2006/xbrldi}explicitMember") is not None:
            continue  # dimensional (segment/line-item) contexts, skip
        s, e = c.find(f".//{XBRLI}startDate"), c.find(f".//{XBRLI}endDate")
        if s is not None and e is not None:
            ctx[c.get("id")] = (s.text, e.text)
    facts = defaultdict(dict)
    for el in root.iter():
        if not isinstance(el.tag, str) or el.get("contextRef") not in ctx:
            continue
        facts[etree.QName(el).localname][el.get("contextRef")] = el.text
    return ctx, facts


def quarter_value(ctx, facts, names):
    """Value for the ~3-month context. Returns (value, context_id) or (None, None)."""
    for n in names:
        for cid, v in facts.get(n, {}).items():
            s, e = ctx[cid]
            days = (datetime.fromisoformat(e) - datetime.fromisoformat(s)).days
            if 80 <= days <= 100 and v not in (None, ""):
                return float(v), cid
    return None, None


def listing(symbol):
    rows = []
    r = get(f"https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly")
    if r is not None and r.status_code == 200:
        for x in r.json():
            rows.append(dict(src="legacy", qe=x["toDate"], cons=x["consolidated"], xbrl=x["xbrl"],
                             bank=x.get("bank"), filed=x.get("filingDate")))
    r = get(f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={symbol}"
            "&type=Integrated%20Filing-%20Financials")
    if r is not None and r.status_code == 200:
        for x in r.json().get("data", []):
            rows.append(dict(src="integrated", qe=x["qe_Date"], cons=x["consolidated"], xbrl=x["xbrl"],
                             bank=None, filed=x.get("broadcast_Date"), sub=x.get("type_Sub")))
    for row in rows:
        row["qe_dt"] = datetime.strptime(row["qe"].title(), "%d-%b-%Y")
        row["is_cons"] = row["cons"] in ("Consolidated",)
    return rows


for sym in SYMBOLS:
    print(f"\n=== {sym}")
    rows = listing(sym)
    if not rows:
        print("  no results listings")
        continue
    quarters = sorted({r["qe_dt"] for r in rows}, reverse=True)
    print(f"  listings: {len(rows)} | quarters {quarters[-1]:%b-%Y} .. {quarters[0]:%b-%Y}")
    print(f"  consolidated available for latest? {any(r['is_cons'] for r in rows if r['qe_dt'] == quarters[0])}")
    revisions = [r for r in rows if r.get("sub") not in (None, "Original")]
    if revisions:
        print(f"  revised filings present: {len(revisions)}")

    # pick: latest, previous quarter, same quarter last year; consolidated preferred
    targets = [quarters[0]] + [q for q in quarters[1:] if (quarters[0] - q).days in range(85, 100)][:1] \
              + [q for q in quarters if (quarters[0] - q).days in range(360, 370)][:1]
    table = {}
    for q in targets:
        cand = [r for r in rows if r["qe_dt"] == q]
        pick = next((r for r in cand if r["is_cons"]), cand[0])
        x = get(pick["xbrl"])
        if x is None or x.status_code != 200:
            continue
        ctx, facts = parse_xbrl(x.content)
        if "InterestExpended" in facts:
            kind, spec = "bank", BANK
        elif "ImpairmentOnFinancialInstruments" in facts and "InterestEarned" in facts:
            kind, spec = "nbfc", NBFC
        else:
            kind, spec = "corporate", NONBANK
        vals = {k: quarter_value(ctx, facts, v)[0] for k, v in spec.items()}
        if kind == "corporate" and None not in (vals["pbt"], vals["finance_costs"], vals["dep"], vals["other_income"]):
            vals["ebitda"] = vals["pbt"] + vals["finance_costs"] + vals["dep"] - vals["other_income"]
        if kind == "bank" and vals["interest_earned"] is not None and vals["interest_expended"] is not None:
            vals["nii"] = vals["interest_earned"] - vals["interest_expended"]
        if kind == "nbfc" and vals["interest_earned"] is not None and vals["finance_costs"] is not None:
            vals["nii"] = vals["interest_earned"] - vals["finance_costs"]
        rounding = next(iter({**facts.get("LevelOfRoundingUsedInFinancialStatements", {}),
                              **facts.get("LevelOfRounding", {})}.values()), "?")
        table[q] = (pick, kind, vals, rounding)

    for q, (pick, kind, vals, rounding) in table.items():
        cr = {k: (round(v / 1e7, 1) if v is not None and k != "gnpa_pct" else v) for k, v in vals.items()}
        print(f"  {q:%b-%Y} [{pick['src']}, {pick['cons']}, {kind}, rounding={rounding}] Rs cr: {cr}")

    if len(table) == 3:
        (q0, (_, _, v0, _)), (q1, (_, _, v1, _)), (q2, (_, _, v2, _)) = list(table.items())
        for k in ("revenue", "ebitda", "nii", "ppop", "pbt", "pat", "pat_owners"):
            if v0.get(k) and v1.get(k) and v2.get(k):
                print(f"    {k:<8} QoQ {100 * (v0[k] / v1[k] - 1):+6.1f}%   YoY {100 * (v0[k] / v2[k] - 1):+6.1f}%")
    else:
        print(f"  only {len(table)} of 3 quarters resolved -> QoQ/YoY incomplete")

print("\n=== results PDF readability (latest 'Outcome of Board Meeting' / result PDFs)")
for sym in SYMBOLS[:3]:
    r = get(f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}")
    if r is None or r.status_code != 200:
        continue
    hit = next((a for a in r.json() if a["desc"] in ("Financial Result Updates", "Outcome of Board Meeting")
                and a["attchmntFile"].lower().endswith(".pdf")), None)
    if not hit:
        print(f"  {sym}: no result PDF found")
        continue
    p = get(hit["attchmntFile"], timeout=60)
    if p is None or p.status_code != 200:
        continue
    with pdfplumber.open(io.BytesIO(p.content)) as pdf:
        pages = len(pdf.pages)
        text = "".join((pg.extract_text() or "") for pg in pdf.pages[:6])
    print(f"  {sym}: {hit['an_dt']} {pages} pages, {len(text):,} chars of text in first 6 pages "
          f"-> {'text PDF' if len(text) > 1500 else 'likely scanned / image PDF'}")
    print("    snippet:", " ".join(text.split())[:220])
