"""Capture real exchange responses as test fixtures.

    python scripts/capture_fixtures.py        (from pipeline/)

Writes into tests/fixtures/. Feeds are trimmed to a handful of <item> blocks,
cut out byte-for-byte; nothing inside an item is edited. Re-running replaces
the fixtures with fresh captures, so the tests must not depend on specific
companies, only on the shape and quirks of the data.
"""
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from finn.http import USER_AGENT

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*"}
RSS = "https://nsearchives.nseindia.com/content/RSS/{}.xml"
ITEM = re.compile(rb"<item>.*?</item>", re.S)


def fetch(url, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)  # no Session: no cookies kept
            break
        except requests.RequestException as e:  # nsearchives times out now and then
            print(f"  attempt {attempt}: {type(e).__name__} {url}")
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)
    print(f"  {r.status_code} {len(r.content):>8,}B {url}")
    time.sleep(1)
    return r


def trim(xml, head, tail=0):
    """Keep the first `head` and last `tail` items, byte-exact."""
    items = list(ITEM.finditer(xml))
    if not items:
        return xml
    idx = sorted(set(range(min(head, len(items)))) | set(range(max(len(items) - tail, 0), len(items))))
    start, end = items[0].start(), items[-1].end()
    return xml[:start] + b"".join(items[i].group(0) for i in idx) + xml[end:]


def save(name, content):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    print(f"    -> {path.relative_to(OUT.parent.parent)}")


def capture_robots():
    manifest = {}
    for host in ["query1.finance.yahoo.com", "finance.yahoo.com", "www.screener.in",
                 "www.nseindia.com", "nsearchives.nseindia.com", "www.bseindia.com", "api.bseindia.com"]:
        r = fetch(f"https://{host}/robots.txt")
        save(f"robots/{host}.txt", r.content)
        manifest[host] = {"status": r.status_code, "content_type": r.headers.get("Content-Type")}
    save("robots/manifest.json", json.dumps(manifest, indent=2).encode())


def capture_rss():
    # Two real polls of the main feed, a few minutes apart, to test overlap/dedup.
    first = fetch(RSS.format("Online_announcements"))
    save("rss/Online_announcements_poll1.xml", trim(first.content, 15))
    etag = first.headers.get("ETag")
    for _ in range(12):
        time.sleep(20)
        second = fetch(RSS.format("Online_announcements"))
        if second.headers.get("ETag") != etag:
            break
    save("rss/Online_announcements_poll2.xml", trim(second.content, 15))

    # Feeds chosen for their quirks: shared links, repeated items, empty and odd timestamps.
    for feed, head, tail in [("Financial_Results", 4, 0), ("InsiderTrading", 50, 0),
                             ("Integrated_Filing_Financials", 3, 0),
                             ("Annual_Reports", 3, 0), ("Offer_Documents", 2, 2),
                             ("Related_Party_Trans", 2, 2), ("Circulars", 3, 0), ("Daily_Buyback", 2, 1)]:
        r = fetch(RSS.format(feed))
        save(f"rss/{feed}.xml", trim(r.content, head, tail))


def capture_truncated():
    """NSE sometimes serves Online_announcements cut off mid-item. When it does,
    keep the first few whole items plus the broken tail exactly as received."""
    r = fetch(RSS.format("Online_announcements"))
    if r.content.rstrip().endswith(b"</rss>"):
        print("    feed is complete right now; existing truncated fixture kept")
        return
    items = list(ITEM.finditer(r.content))
    head = r.content[:items[0].start()] + b"".join(m.group(0) for m in items[:5])
    save("rss/Online_announcements_truncated.xml", head + r.content[items[-1].end():])


def capture_api():
    # Yesterday and today, so the fixture straddles midnight (tests day partitioning).
    today = date.today()
    r = fetch("https://www.nseindia.com/api/corporate-announcements?index=equities"
              f"&from_date={today - timedelta(days=1):%d-%m-%Y}&to_date={today:%d-%m-%Y}")
    items = r.json()  # newest first
    older = [a for a in items if not a["sort_date"].startswith(f"{today:%Y-%m-%d}")]
    pick = items[:5] + older[:3]
    pick += [a for a in items if not a["attchmntFile"].lower().endswith(".pdf") and a not in pick][:1]
    save("api/announcements.json", json.dumps(pick, indent=1, ensure_ascii=False).encode("utf-8"))


# --- the Brief -----------------------------------------------------------------------
# Real cases for each classification rule: (case, NSE subject, summary must match, must not match).
CASES = [
    ("results_outcome", "Outcome of Board Meeting", r"financial results", None),
    ("results_press_q", "Press Release", r"Q[1-4]\s*FY", None),
    ("investor_presentation", "Investor Presentation", r"", None),
    ("integrated_financial", "Integrated Filing- Financial", r"", None),
    ("mgmt_top", "Appointment", r"Chief Executive|CEO|Managing Director|Chief Financial", None),
    ("mgmt_other", "Appointment", r"Independent Director|Senior Management|Company Secretary",
     r"Chief|CEO|CFO|Managing|Chairman|Whole|Executive Director"),
    ("change_in_management", "Change in Management", r"", r"Chief|CEO|CFO|Managing|Chairman"),
    ("auditor_change", "Change in Auditors", r"", None),
    ("acquisition", "Acquisition", r"", None),
    ("litigation", "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company", r"", None),
    ("material_issue", "Disclosure of material issue", r"", None),
    ("board_fund_raise", "Outcome of Board Meeting", r"raising of fund|preferential|\bQIP\b", r"financial results"),
    ("board_dividend", "Outcome of Board Meeting", r"dividend", r"financial results|raising"),
    ("credit_rating", "Credit Rating", r"", r"downgrad|negative|watch"),
    ("orders", "Bagging/Receiving of orders/contracts", r"", None),
    ("news_verification", "News Verification", r"", None),
    ("transcript", "Analysts/Institutional Investor Meet/Con. Call Updates", r"transcript", None),
    ("meeting_schedule", "Analysts/Institutional Investor Meet/Con. Call Updates", r"schedule",
     r"transcript|recording|audio"),
    ("newspaper", "Copy of Newspaper Publication", r"", None),
    ("rta_update", "Updates", r"\bRTA\b|Registrar", None),
    ("record_date_dividend", "Record Date", r"dividend", None),
    ("double_spaced_subject", "Final  forensic  audit  report", r"", None),
    ("general_update_unknown", "General Updates", r"Media Statement|Statement", r"RTA|Registrar|transcript|order"),
]
BRIEF_SYMBOLS = ["KEC", "SBIN", "MEDANTA", "RELIANCE", "MOLDTKPAC", "JSWDULUX"]
XBRL_KEEP = {"RevenueFromOperations", "ProfitBeforeTax", "FinanceCosts", "DepreciationDepletionAndAmortisationExpense",
             "OtherIncome", "ProfitLossForPeriod", "InterestEarned", "InterestExpended",
             "OperatingProfitBeforeProvisionAndContingencies", "ProfitLossFromOrdinaryActivitiesBeforeTax",
             "ProfitLossForThePeriod", "ImpairmentOnFinancialInstruments", "NameOfTheCompany", "Symbol"}
PDF_CASES = ["ALKEM_03112026133322", "KEC_02112026211334", "UPL_02112026153430", "UPL_02112026153604",
             "HAL_28102026180358", "TRENT_29102026163122", "DIXON_30102026160939"]


def _trim_xbrl(blob):
    """Keep contexts, units and only the facts the Brief reads; values untouched."""
    from lxml import etree
    root = etree.fromstring(blob)
    for el in list(root):
        if not isinstance(el.tag, str) or el.get("contextRef") is None:
            continue
        if etree.QName(el).localname not in XBRL_KEEP:
            root.remove(el)
    used = {el.get("contextRef") for el in root if isinstance(el.tag, str)}
    for el in list(root):
        if isinstance(el.tag, str) and etree.QName(el).localname == "context" and el.get("id") not in used:
            root.remove(el)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def capture_brief():
    import io
    import zipfile

    from finn.archive import Archive

    data = Path(__file__).resolve().parents[2] / "data"

    today = date.today()
    items = fetch("https://www.nseindia.com/api/corporate-announcements?index=equities"
                  f"&from_date={today - timedelta(days=7):%d-%m-%Y}&to_date={today:%d-%m-%Y}").json()
    cases = []
    for case, desc, want, avoid in CASES:
        hit = next((a for a in items if a["desc"] == desc and re.search(want, a["attchmntText"], re.I)
                    and not (avoid and re.search(avoid, a["attchmntText"], re.I))), None)
        if hit:
            cases.append({"case": case, "item": hit})
        else:
            print(f"    no live example for {case} this week")
    save("brief/classify_cases.json", json.dumps(cases, indent=1, ensure_ascii=False).encode("utf-8"))

    for path in sorted((data / "cache" / "bhavcopy").glob("*.csv.zip")):
        with zipfile.ZipFile(path) as zf:
            name = zf.namelist()[0]
            lines = zf.read(name).decode("utf-8").splitlines(keepends=True)
        header, rows = lines[0], [row for row in lines[1:] if row.split(",")[7] in BRIEF_SYMBOLS]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(name, header + "".join(rows))
        save(f"brief/bhavcopy/{path.name}", buf.getvalue())

    acts = fetch("https://www.nseindia.com/api/corporates-corporateActions?index=equities"
                 "&from_date=01-10-2026&to_date=03-11-2026").json()
    for sym in BRIEF_SYMBOLS:
        cached = data / "cache" / "nse_api" / "corporate_actions" / f"{sym}.json"
        rows = json.loads(cached.read_text("utf-8")) if cached.exists() else [a for a in acts if a["symbol"] == sym]
        save(f"brief/corporate_actions/{sym}.json", json.dumps(rows, indent=1).encode())

    for sym in ["MEDANTA", "SBIN", "BAJAJFINSV"]:
        listing = json.loads((data / "cache" / "nse_api" / "integrated_filings" / f"{sym}.json").read_text("utf-8"))
        save(f"brief/integrated_filings/{sym}.json", json.dumps(listing, indent=1).encode())
        for row in listing:
            src = data / "cache" / "xbrl" / Path(row["xbrl"]).name
            if src.exists():
                save(f"brief/xbrl/{src.name}", _trim_xbrl(src.read_bytes()))

    for path in sorted((data / "cache" / "pdf_text").glob("*.json")):
        if any(path.name.startswith(p) for p in PDF_CASES):
            save(f"brief/pdf_text/{path.name}", path.read_bytes())

    keep = {"KEC", "SBIN", "MEDANTA", "RELIANCE", "ALKEM", "BAJAJFINSV", "UPL", "ITC"}
    rows = [r for r in Archive(data, "nse_api/announcements").rows()
            if r["item"].get("symbol") in keep and (r["published"] or "")[:10] in ("2026-11-02", "2026-11-03")]
    save("brief/announcements.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))
    eq = (data / "cache" / "nse" / "EQUITY_L.csv").read_text("utf-8").splitlines(keepends=True)
    symbols = keep | set(BRIEF_SYMBOLS)
    save("brief/EQUITY_L.csv", (eq[0] + "".join(row for row in eq[1:] if row.split(",")[0] in symbols)).encode())


LLM_DOCS = ["ITC_02112026184512_SE_Sproutlife_.pdf", "HDFCBANK3_31102026221631_SE_INTIMATION-_Sanjay_Dsouza.pdf",
            "TRENT_29102026163044_AppointmentofDirector.pdf", "TRENT_29102026163102_AppointmentofDirector.pdf"]


def capture_llm():
    """Text of real filings (as the pipeline extracted it) and their NSE records, for the model tests."""
    from finn.archive import Archive
    data = Path(__file__).resolve().parents[2] / "data"
    for name in LLM_DOCS:
        save(f"llm/pdf_text/{name}.json", (data / "cache" / "pdf_text" / f"{name}.json").read_bytes())
    wanted = {f"https://nsearchives.nseindia.com/corporate/{n}" for n in LLM_DOCS}
    rows = [r for r in Archive(data, "nse_api/announcements").rows() if r["item"].get("attchmntFile") in wanted]
    save("llm/announcements.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))


if __name__ == "__main__":
    steps = {"robots": capture_robots, "api": capture_api, "rss": capture_rss, "truncated": capture_truncated,
             "brief": capture_brief, "llm": capture_llm}
    for name in sys.argv[1:] or steps:
        steps[name]()
