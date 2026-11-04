"""Check every figure and label the Brief screen shows against the source files it links.

    python pipeline/scripts/verify_brief.py [http://localhost:3000]     (from the repo root)

Reads the server-rendered page for each window, then re-derives each number on
its own: XBRL facts by regex, prices and volumes from the bhavcopy CSVs, and
appointee profiles from the PDFs with pdfplumber. It does not reuse the finn.brief
code that built the page, so a bug there cannot hide here.
"""
import csv
import io
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pdfplumber
import requests
from lxml import html

sys.stdout.reconfigure(encoding="utf-8")  # problems quote "→" and "₹", which a Windows console can't encode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = DATA / "cache"
BASE = next((a for a in sys.argv[1:] if not a.startswith("--")), "http://localhost:3000")
IST = "+05:30"
MINUS = "−"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

checks = Counter()
problems = []


def ok(cond, what):
    checks["checked"] += 1
    if not cond:
        problems.append(what)


# --- display rules, re-implemented (Intl en-IN rounds half away from zero) --------------

def _indian(int_part):
    s = str(int_part)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def fmt(x, digits):
    d = Decimal(repr(abs(x))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    whole, _, frac = f"{d:.{digits}f}".partition(".")
    return _indian(int(whole)) + (f".{frac}" if digits else "")


def crore(rupees):
    cr = rupees / 1e7
    s = fmt(cr, 0 if abs(cr) >= 1000 else 1)
    return (MINUS if cr < 0 and s.strip("0.,") else "") + s


def pct(p):
    if p is None:
        return "n/m"
    s = fmt(p, 1)
    return f"{'+' if p > 0 else MINUS if p < 0 else ''}{s}%"


def change(now, then):
    return None if now is None or then is None or then <= 0 else (now / then - 1) * 100


def ist_short(iso):
    dt = datetime.fromisoformat(iso)
    return f"{dt.day} {MONTHS[dt.month - 1]}, {dt:%H:%M}"


def day_long(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def text(el):
    return " ".join(el.text_content().split())


# --- independent source readers --------------------------------------------------------

def xbrl_quarter(path, quarter_end):
    """{element: value} for the 3-month, non-dimensional context ending on quarter_end."""
    t = path.read_text(encoding="utf-8")
    ctx = set()
    for m in re.finditer(r"<xbrli:context id=\"([^\"]+)\">(.*?)</xbrli:context>", t, re.S):
        body = m.group(2)
        if "explicitMember" in body:
            continue
        s = re.search(r"<xbrli:startDate>([\d-]+)</xbrli:startDate>", body)
        e = re.search(r"<xbrli:endDate>([\d-]+)</xbrli:endDate>", body)
        if s and e and e.group(1) == quarter_end:
            days = (datetime.fromisoformat(e.group(1)) - datetime.fromisoformat(s.group(1))).days
            if 80 <= days <= 100:
                ctx.add(m.group(1))
    facts = {}
    for m in re.finditer(r"<[\w-]+:(\w+)\b[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]+)</", t):
        if m.group(2) in ctx and re.fullmatch(r"-?[\d.]+", m.group(3).strip()):
            facts.setdefault(m.group(1), float(m.group(3)))
    return facts


DEFS = {
    "Revenue": lambda f: f.get("RevenueFromOperations"),
    "EBITDA": lambda f: None if any(k not in f for k in ("ProfitBeforeTax", "FinanceCosts", "OtherIncome")) or
    not ("DepreciationDepletionAndAmortisationExpense" in f or "DepreciationAndAmortisationExpense" in f) else
    f["ProfitBeforeTax"] + f["FinanceCosts"] + f.get("DepreciationDepletionAndAmortisationExpense",
                                                     f.get("DepreciationAndAmortisationExpense", 0)) - f["OtherIncome"],
    "PBT": lambda f: f.get("ProfitBeforeTax", f.get("ProfitLossFromOrdinaryActivitiesBeforeTax")),
    "PAT": lambda f: f.get("ProfitLossForPeriod", f.get("ProfitLossForThePeriod")),
    "Pre-provision profit": lambda f: f.get("OperatingProfitBeforeProvisionAndContingencies"),
}


def metric(label, facts, bank):
    if label == "Net interest income":
        if bank:
            return facts["InterestEarned"] - facts["InterestExpended"]
        return facts["InterestEarned"] - facts["FinanceCosts"]
    if label == "PBT" and bank:
        return facts.get("ProfitLossFromOrdinaryActivitiesBeforeTax", facts.get("ProfitBeforeTax"))
    if label == "PAT" and bank:
        return facts.get("ProfitLossForThePeriod", facts.get("ProfitLossForPeriod"))
    return DEFS[label](facts)


def bhav_row(url, symbol):
    path = CACHE / "bhavcopy" / url.rsplit("/", 1)[1]
    with zipfile.ZipFile(path) as zf, zf.open(zf.namelist()[0]) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
            if r["TckrSymb"] == symbol and r["SctySrs"] in ("EQ", "BE", "BZ"):
                return r
    return None


_pdf_cache = {}


def pdf_pages(url):
    if url not in _pdf_cache:
        with pdfplumber.open(CACHE / "pdf" / url.rsplit("/", 1)[1]) as pdf:
            _pdf_cache[url] = [p.extract_text() or "" for p in pdf.pages[:6]]
    return _pdf_cache[url]


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def profile_match(quote, url, page):
    """How the quoted profile was found on that PDF page: as running text, as one table
    cell (two-column disclosure tables read row by row in pdfplumber), or word by word."""
    q = squash(quote)
    if q in squash(pdf_pages(url)[page - 1]):
        return "running text"
    with pdfplumber.open(CACHE / "pdf" / url.rsplit("/", 1)[1]) as pdf:
        cells = [c for t in pdf.pages[page - 1].extract_tables() for row in t for c in row if c]
    if any(q in squash(c) for c in cells):
        return "table cell"
    words = re.findall(r"[a-z0-9]+", quote.lower())
    page_words = re.findall(r"[a-z0-9]+", pdf_pages(url)[page - 1].lower())
    tri = {tuple(page_words[i:i + 3]) for i in range(len(page_words) - 2)}
    qtri = [tuple(words[i:i + 3]) for i in range(len(words) - 2)]
    if set(words) <= set(page_words) and sum(t in tri for t in qtri) >= 0.9 * len(qtri):
        return "words and 90%+ of 3-word runs"
    return "nothing"


announcements = {}
for f in (DATA / "raw" / "nse_api" / "announcements").glob("*.jsonl"):
    for line in f.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        announcements.setdefault(r["item"].get("attchmntFile"), []).append(r)
portfolio = json.loads((ROOT / "config" / "portfolio.json").read_text())
sessions = sorted(p.name for p in (CACHE / "bhavcopy").glob("*.csv.zip"))


# --- per window ------------------------------------------------------------------------------

def rendered(url):
    """The page as the browser shows it. React streams parts of a large page as hidden
    segments with id="S:n" that its runtime moves into <template id="P:n"> holes; do the same.
    A segment is a <div> in normal flow, but a <tbody>, <tr> and so on inside tables."""
    tree = html.fromstring(requests.get(url, timeout=60).content.decode("utf-8"))
    for _ in range(500):
        moved = False
        for hole in tree.xpath('//template[starts-with(@id, "P:")]'):
            found = tree.xpath(f'//*[@id="S:{hole.get("id")[2:]}"]')
            if not found:
                continue
            seg, parent = found[0], hole.getparent()
            at, tail = parent.index(hole), hole.tail or ""
            if seg.text:   # text before the segment's first child joins whatever precedes the hole
                if at == 0:
                    parent.text = (parent.text or "") + seg.text
                else:
                    parent[at - 1].tail = (parent[at - 1].tail or "") + seg.text
            children = list(seg)
            parent.remove(hole)
            for k, child in enumerate(children):   # move, as React's $RS does: no copy is left behind
                parent.insert(at + k, child)
            if children:
                children[-1].tail = (children[-1].tail or "") + tail
            elif at:
                parent[at - 1].tail = (parent[at - 1].tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
            box = seg.getparent()
            box.remove(seg)
            # drop the now-empty hidden wrappers (<table hidden><tbody>) the segment travelled in
            while box is not None and len(box) == 0 and box.tag in ("tbody", "thead", "tr", "table", "div") \
                    and (box.get("hidden") is not None or box.tag in ("tbody", "thead", "tr")):
                up = box.getparent()
                if up is None:
                    break
                up.remove(box)
                box = up
            moved = True
        if not moved:
            break
    return tree


def verify(window):
    url = BASE + ("/" if window == "24h" else f"/?w={window}")
    doc = rendered(url)
    brief = json.loads((DATA / "brief" / f"brief-{window}.json").read_text(encoding="utf-8"))
    start, end = datetime.fromisoformat(brief["window"]["start"]), datetime.fromisoformat(brief["window"]["end"])
    tag = f"[{window}]"

    # tally + window line
    stats = [int(b.text_content()) for b in doc.cssselect(".tally .stat b")]
    needs = doc.cssselect("#needs article.card")
    worth = doc.cssselect("#worth article.card")
    receipt = doc.cssselect("#routine .receipt-group li")
    ok(stats == [len(needs), len(worth), len(receipt)],
       f"{tag} tally {stats} vs cards {len(needs)}/{len(worth)}/{len(receipt)}")
    window_line = text(doc.cssselect(".intro .fine")[0])
    ok(window_line.startswith(f"{ist_short(brief['window']['start'])} → {ist_short(brief['window']['end'])} IST"),
       f"{tag} window line {window_line!r}")
    ok(end - start == timedelta(hours={"24h": 24, "3d": 72, "7d": 168}[window]), f"{tag} window length")

    in_window = [r for rs in announcements.values() for r in rs
                 if r["item"].get("symbol") in portfolio["holdings"] and r["published"]
                 and start <= datetime.fromisoformat(r["published"]) <= end]
    in_window = list({r["key"]: r for r in in_window}.values())
    checked = text(doc.cssselect(".checked")[0])
    m = re.search(r"Checked (\d+) filings from (\d+) of your (\d+) companies", checked)
    ok(m and int(m.group(1)) == len(in_window), f"{tag} filings checked {m and m.group(1)} vs raw {len(in_window)}")
    ok(m and int(m.group(2)) == len({r['item']['symbol'] for r in in_window}), f"{tag} companies with filings")
    ok(m and int(m.group(3)) == len(portfolio["holdings"]), f"{tag} portfolio size")
    closes = [s for s in sessions if start <= datetime.strptime(re.search(r"_(\d{8})_F", s).group(1) + " 15:30" + IST,
                                                                  "%Y%m%d %H:%M%z") <= end]
    for s in closes:
        d = datetime.strptime(re.search(r"_(\d{8})_F", s).group(1), "%Y%m%d")
        ok(day_long(d) in checked, f"{tag} session {s} not listed in checked line")
    shown_filings = 0

    for art in needs + worth:
        cid = art.get("data-card")
        sym = text(art.cssselect(".ticker")[0])
        where = f"{tag} {cid}"
        ok(cid.startswith(sym + ":"), f"{where} ticker {sym}")

        # filings: link, subject, time, symbol, window
        rows = art.cssselect(".sources .src-list > li:not(.lookback)")
        filing_rows = [li for li in rows if li.cssselect("a") and ("PDF" in text(li.cssselect("a")[-1]))
                       or "no attachment" in text(li)]
        for li in filing_rows:
            a = li.cssselect("a")
            href = a[-1].get("href") if a else None
            subject = text(li.cssselect(".src-what")[0])
            when = text(li.cssselect(".src-when")[0])
            raws = announcements.get(href) or [
                r for rs in announcements.values() for r in rs
                if r["item"]["symbol"] == sym and r["item"]["desc"].split() == subject.split()]
            match = [r for r in raws if ist_short(r["published"]) == when and r["item"]["symbol"] == sym]
            ok(bool(match), f"{where} filing {subject} {when} {href} not found in raw announcements")
            if match:
                ok(start <= datetime.fromisoformat(match[0]["published"]) <= end, f"{where} filing outside window")
                ok(" ".join(match[0]["item"]["desc"].split()) == subject, f"{where} subject {subject!r}")
            shown_filings += 1

        # card time = lead filing time (or 15:30 session close)
        when = art.cssselect("time.when")[0]
        ok(text(when) == ist_short(when.get("datetime")), f"{where} card time display")

        # evidence quotes NSE's subject
        ev = [text(e) for e in art.cssselect(".why .evidence")]
        if filing_rows and ev:
            ok(any(s in ev[0] for s in [text(li.cssselect(".src-what")[0]) for li in filing_rows])
               or ev[0].startswith("Filing text:"), f"{where} evidence {ev[0]!r} does not quote a subject")

        # results figures
        xml_links = [a.get("href") for a in art.cssselect(".sources a") if text(a) == "XML"]
        tables = art.cssselect("table.figures")
        if tables and xml_links:
            q_labels = [text(th) for th in tables[1].cssselect("thead th")[1:]]
            files = [CACHE / "xbrl" / h.rsplit("/", 1)[1] for h in xml_links]
            qends = []
            for li in art.cssselect(".sources .src-list > li"):
                what = text(li.cssselect(".src-what")[0]) if li.cssselect(".src-what") else ""
                m = re.match(r"Results XBRL, (Q(\d) FY(\d\d))", what)
                if m:
                    q, fy = int(m.group(2)), 2000 + int(m.group(3))
                    month = {1: 6, 2: 9, 3: 12, 4: 3}[q]
                    year = fy - 1 if q < 4 else fy
                    qends.append(f"{year}-{month:02d}-{ {3: 31, 6: 30, 9: 30, 12: 31}[month]}")
            facts = [xbrl_quarter(f, q) for f, q in zip(files, qends, strict=True)]
            bank = "InterestExpended" in facts[0]
            xbrl_items = [text(w) for w in art.cssselect(".sources .src-list > li > .src-what")
                          if text(w).startswith("Results XBRL")]
            ok(q_labels[:len(qends)] == [t.split(", ")[1].split(" (")[0] for t in xbrl_items],
               f"{where} quarter headers {q_labels}")
            for tr in tables[0].cssselect("tbody tr"):
                label = text(tr.cssselect("th")[0]).rstrip("*").strip()
                cells = [text(td) for td in tr.cssselect("td")]
                vals = [metric(label, f, bank) if f else None for f in facts] + [None] * (3 - len(facts))
                qoq, yoy = pct(change(vals[0], vals[1])), pct(change(vals[0], vals[2]))
                ok(cells[0] == crore(vals[0]), f"{where} {label} value {cells[0]} vs source {crore(vals[0])}")
                ok(cells[1] == qoq, f"{where} {label} QoQ {cells[1]} vs {qoq}")
                ok(cells[2] == yoy, f"{where} {label} YoY {cells[2]} vs {yoy}")
            for tr in tables[1].cssselect("tbody tr"):
                label = text(tr.cssselect("th")[0])
                cells = [text(td) for td in tr.cssselect("td")]
                for i, f in enumerate(facts):
                    ok(cells[i] == crore(metric(label, f, bank)), f"{where} {label} quarter {i} {cells[i]}")
            headline = text(art.cssselect(".headline")[0])
            ok(headline == f"{q_labels[0]} results", f"{where} headline {headline!r}")

        # moves: each move with an average has its own list of earlier files, in the same order
        lookbacks = iter(art.cssselect(".sources .lookback"))
        for mv in art.cssselect(".move"):
            day_txt = text(mv.cssselect(".move-day")[0])
            src = [a.get("href") for a in art.cssselect(".sources a") if text(a) == "ZIP"]
            d = datetime.strptime(day_txt, "%d %b %Y")
            href = next(h for h in src if f"_{d:%Y%m%d}_F_" in h)
            row = bhav_row(href, sym)
            close, prev, vol = float(row["ClsPric"]), float(row["PrvsClsgPric"]), int(float(row["TtlTradgVol"]))
            main = text(mv.cssselect(".move-main")[0])
            ok(f"close ₹{fmt(close, 2)}" in main, f"{where} close in {main!r}")
            ok(f"vs ₹{fmt(prev, 2)}" in main, f"{where} prev close in {main!r}")
            ok(pct((close / prev - 1) * 100) in main, f"{where} change in {main!r}")
            vol_line = text(mv.cssselect(".move-vol")[0])
            ok(f"Volume {fmt(vol, 0)} shares" in vol_line, f"{where} volume in {vol_line!r}")
            if "average of" in vol_line:
                block = next(lookbacks)
                lb = block.cssselect("ol li a")
                files = [a.get("href") for a in lb]
                want = [s for s in sessions if s < href.rsplit("/", 1)[1]][-20:]
                ok([f.rsplit("/", 1)[1] for f in files] == want, f"{where} lookback is not the 20 prior sessions")
                vols = [int(float(bhav_row(f, sym)["TtlTradgVol"])) for f in files]
                avg = sum(vols) / len(vols)
                ok(f"average of {fmt(avg, 0)}" in vol_line, f"{where} average in {vol_line!r} vs {fmt(avg, 0)}")
                ok(f"{fmt(vol / avg, 1)}×" in vol_line, f"{where} multiple in {vol_line!r} vs {fmt(vol / avg, 1)}")
                listed = [text(li.cssselect(".num")[0]) for li in block.cssselect("ol li")]
                ok(listed == [fmt(v, 0) for v in vols], f"{where} lookback volumes listed")
                hit_v = vol / avg >= portfolio["thresholds"]["volume_multiple"]
                hit_p = abs((close / prev - 1) * 100) >= portfolio["thresholds"]["price_move_pct"]
                ok(hit_v or hit_p, f"{where} shown as unusual but crosses no threshold")

        # profile quote, against pdfplumber's reading of that page (a different library from the pipeline's)
        for fig in art.cssselect("figure.profile"):
            quote = text(fig.cssselect("blockquote")[0]).rstrip("…")
            pdf = fig.cssselect("a")[0].get("href")
            page = int(re.search(r"page (\d+)", text(fig.cssselect("figcaption")[0])).group(1))
            how = profile_match(quote, pdf, page)
            checks[f"profile matched by {how}"] += 1
            ok(how != "nothing", f"{where} profile text not on page {page} of {pdf}")

        # model-read claims: each quote must be on the stated page of the linked PDF (read by pdfplumber)
        for q in art.cssselect(".ai-quote"):
            quote = text(q.cssselect("blockquote")[0])
            pdf = q.cssselect("a")[0].get("href")
            m = re.search(r"page (\d+)", text(q.cssselect("summary")[0]))
            how = profile_match(quote, pdf, int(m.group(1))) if m else "nothing"
            checks[f"model quote matched by {how}"] += 1
            ok(how != "nothing", f"{where} model quote not on the stated page of {pdf}: {quote[:60]!r}")

    receipt_ids = len(receipt)
    ok(shown_filings + receipt_ids == len(in_window),
       f"{tag} filings on cards ({shown_filings}) + routine ({receipt_ids}) != filings in window ({len(in_window)})")
    return doc


def check_links(docs):
    from finn.http import Blocked, Client, FetchError
    client = Client(min_interval=0.3)
    hrefs = sorted({a.get("href") for d in docs for a in d.cssselect("a[href^='http']")})
    for h in hrefs:
        try:
            r = client.session.head(h, timeout=30, allow_redirects=True)
            status = r.status_code
            if status in (403, 405):    # some hosts refuse HEAD; ask for the first byte instead
                status = client.get(h).status_code
        except (Blocked, FetchError, requests.RequestException) as e:
            status = f"{type(e).__name__}: {e}"
        ok(status == 200, f"link {h} -> {status}")
    return len(hrefs)


if __name__ == "__main__":
    docs = [verify(w) for w in ("24h", "3d", "7d")]
    before = checks["checked"]
    n_links = check_links(docs) if "--links" in sys.argv else 0
    print(f"{before} figure/label checks, {n_links} links checked, {len(problems)} problems")
    for p in problems:
        print("  PROBLEM", p)
