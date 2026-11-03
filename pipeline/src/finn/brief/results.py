"""Headline numbers from NSE's structured (XBRL) results filings.

Each figure is a reported XBRL fact, or a sum/difference of reported facts
with the formula stated. Nothing is estimated. Banks and NBFCs file
different taxonomies and have no EBITDA, so they get their own metrics.
"""
from datetime import date, datetime

from lxml import etree

XBRLI = "{http://www.xbrl.org/2003/instance}"
DIM = "{http://xbrl.org/2006/xbrldi}explicitMember"

# metric key -> (label, how it is computed: [(sign, [candidate element names])])
METRICS = {
    "corporate": [
        ("revenue", "Revenue", [(+1, ["RevenueFromOperations"])]),
        ("ebitda", "EBITDA", [(+1, ["ProfitBeforeTax"]), (+1, ["FinanceCosts"]),
                              (+1, ["DepreciationDepletionAndAmortisationExpense",
                                    "DepreciationAndAmortisationExpense"]),
                              (-1, ["OtherIncome"])]),
        ("pbt", "PBT", [(+1, ["ProfitBeforeTax"])]),
        ("pat", "PAT", [(+1, ["ProfitLossForPeriod", "ProfitLossForThePeriod"])]),
    ],
    "bank": [
        ("nii", "Net interest income", [(+1, ["InterestEarned"]), (-1, ["InterestExpended"])]),
        ("ppop", "Pre-provision profit", [(+1, ["OperatingProfitBeforeProvisionAndContingencies"])]),
        ("pbt", "PBT", [(+1, ["ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeTax"])]),
        ("pat", "PAT", [(+1, ["ProfitLossForThePeriod", "ProfitLossForPeriod"])]),
    ],
    "nbfc": [
        ("revenue", "Revenue", [(+1, ["RevenueFromOperations"])]),
        ("nii", "Net interest income", [(+1, ["InterestEarned"]), (-1, ["FinanceCosts"])]),
        ("pbt", "PBT", [(+1, ["ProfitBeforeTax"])]),
        ("pat", "PAT", [(+1, ["ProfitLossForPeriod"])]),
    ],
}
KIND_NOTE = {
    "corporate": "EBITDA is computed: PBT + finance costs + depreciation & amortisation − other income.",
    "bank": "Banks report no revenue or EBITDA. "
            "Net interest income is computed as interest earned − interest expended.",
    "nbfc": "Lenders have no EBITDA. Net interest income is computed as interest earned − finance costs.",
}


def parse(blob):
    """(contexts, facts): contexts {id: (start, end)} without dimensions; facts {name: {ctx: text}}."""
    root = etree.fromstring(blob)
    ctx = {}
    for c in root.iter(XBRLI + "context"):
        if c.find(f".//{DIM}") is not None:
            continue
        s, e = c.find(f".//{XBRLI}startDate"), c.find(f".//{XBRLI}endDate")
        if s is not None and e is not None:
            ctx[c.get("id")] = (date.fromisoformat(s.text.strip()), date.fromisoformat(e.text.strip()))
    facts = {}
    for el in root.iter():
        if isinstance(el.tag, str) and el.get("contextRef") in ctx and (el.text or "").strip():
            facts.setdefault(etree.QName(el).localname, {})[el.get("contextRef")] = el.text.strip()
    return ctx, facts


def kind_of(facts):
    if "InterestExpended" in facts:
        return "bank"
    if "InterestEarned" in facts and "ImpairmentOnFinancialInstruments" in facts:
        return "nbfc"
    if "RevenueFromOperations" in facts and "ProfitBeforeTax" in facts:
        return "corporate"
    return None


def _quarter_fact(ctx, facts, names, quarter_end):
    """(element, value) for the three-month period ending on quarter_end."""
    for name in names:
        for cid, text in facts.get(name, {}).items():
            start, end = ctx[cid]
            if end == quarter_end and 80 <= (end - start).days <= 100:
                return name, float(text)
    return None, None


def quarter(blob, quarter_end):
    """{"kind", "values": {metric: {"value", "inputs": [(sign, element, value)]}}} or kind None."""
    ctx, facts = parse(blob)
    kind = kind_of(facts)
    if kind is None:
        return {"kind": None, "values": {}}
    values = {}
    for key, _label, terms in METRICS[kind]:
        inputs = []
        for sign, names in terms:
            element, v = _quarter_fact(ctx, facts, names, quarter_end)
            if element is None:
                inputs = None
                break
            inputs.append((sign, element, v))
        if inputs:
            values[key] = {"value": sum(s * v for s, _, v in inputs), "inputs": inputs}
    return {"kind": kind, "values": values}


def change_pct(now, then):
    """% change, or None when the base is missing or not positive (a change from a loss is not meaningful)."""
    if now is None or then is None or then <= 0:
        return None
    return (now / then - 1) * 100


def fy_quarter_label(quarter_end):
    """Indian fiscal quarters: Apr-Jun is Q1; FY27 ends March 2027."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}[quarter_end.month]
    fy = quarter_end.year + (1 if quarter_end.month > 3 else 0)
    return f"Q{q} FY{fy % 100:02d}"


def parse_qe(text):
    return datetime.strptime(text.strip().title(), "%d-%b-%Y").date()


def quarter_back(qe, quarters):
    """The quarter-end date `quarters` quarters before qe (qe is always a month end)."""
    month = qe.month - 3 * quarters
    year = qe.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, last)


def _stamp(row):
    from finn.times import parse_exchange_time
    stamps = [parse_exchange_time(row.get(k)) for k in ("revised_Date", "broadcast_Date", "creation_Date")]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def pick_filings(listing, filed_at):
    """The XBRL filings behind a results announcement made at `filed_at`.

    The current quarter is the one whose integrated filing NSE published within
    a day before to three days after the announcement. Previous and year-ago
    quarters use the same basis (consolidated if the company filed one). For
    each quarter the latest revision wins. Returns None if nothing matches yet.
    """
    rows = []
    for r in listing:
        if not r.get("xbrl") or not r.get("qe_Date"):
            continue
        rows.append({**r, "_qe": parse_qe(r["qe_Date"]), "_at": _stamp(r)})
    near = [r for r in rows if r["_at"] and -86400 <= (r["_at"] - filed_at).total_seconds() <= 3 * 86400]
    if not near:
        return None
    qe = max(r["_qe"] for r in near)
    basis = "Consolidated" if any(r["_qe"] == qe and r.get("consolidated") == "Consolidated" for r in near) \
        else "Standalone"

    def best(q):
        cands = [r for r in rows if r["_qe"] == q and r.get("consolidated") == basis]
        return max(cands, key=lambda r: r["_at"].timestamp() if r["_at"] else 0) if cands else None

    return {"basis": basis, "quarter_end": qe,
            "current": best(qe), "previous": best(quarter_back(qe, 1)), "year_ago": best(quarter_back(qe, 4))}
