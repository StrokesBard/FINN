"""Fetch and cache everything the Brief is built from. Network only; no ranking here.

    data/raw/nse_api/announcements/*.jsonl     filings (the same archive `finn archive` writes)
    data/cache/nse/EQUITY_L.csv                NSE's symbol master
    data/cache/bhavcopy/*.csv.zip              daily price files, exactly as published
    data/cache/nse_api/<kind>/<SYMBOL>.json    corporate actions, integrated-filing listings
    data/cache/xbrl/*.xml                      results XBRL, immutable once published
    data/cache/pdf/*.pdf + pdf_text/*.json     management-change filings and their text
"""
import io
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pypdf

from finn.archive import Archive
from finn.brief import classify as cls
from finn.brief import prices, results
from finn.http import Blocked, FetchError
from finn.sources import nse_announcements
from finn.times import parse_exchange_time

log = logging.getLogger(__name__)

API = "https://www.nseindia.com/api"
ANNOUNCEMENTS = (API + "/corporate-announcements?index=equities&symbol={sym}"
                 "&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}")
CORPORATE_ACTIONS = API + "/corporates-corporateActions?index=equities&symbol={sym}"
INTEGRATED = API + "/integrated-filing-results?index=equities&symbol={sym}&type=Integrated%20Filing-%20Financials"
EQUITY_L = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
PDF_PAGES = 6  # the profile and the role are always on the first pages


def load_portfolio(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cache_dir(data_dir, *parts):
    d = Path(data_dir, "cache", *parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def pdf_text_path(data_dir, url):
    return Path(data_dir, "cache", "pdf_text", Path(url).name + ".json")


def collect(client, data_dir, portfolio, now, days=7):
    """Returns a list of (step, ok, detail) lines for the CLI to print."""
    report = []
    symbols = portfolio["holdings"]

    def step(name, fn):
        try:
            detail = fn()
            report.append((name, True, detail))
        except (Blocked, FetchError) as e:
            report.append((name, False, str(e)))

    def master():
        r = client.get(EQUITY_L)
        (cache_dir(data_dir, "nse") / "EQUITY_L.csv").write_bytes(r.content)
        known = {line.split(",")[0] for line in r.text.splitlines()[1:]}
        missing = [s for s in symbols if s not in known]
        if missing:
            raise FetchError(f"not NSE equity symbols: {', '.join(missing)}")
        return f"{len(symbols)} symbols verified against EQUITY_L.csv"
    step("symbol master", master)

    archive = Archive(data_dir, nse_announcements.SOURCE)
    start = (now - timedelta(days=days)).date()
    for sym in symbols:
        def announcements(sym=sym):
            r = client.get(ANNOUNCEMENTS.format(sym=quote(sym), start=start, end=now.date()))
            recs = nse_announcements.parse(r.json(), now)
            return f"{len(recs)} filings, {len(archive.add(recs))} new"
        step(f"announcements {sym}", announcements)

        def actions(sym=sym):
            r = client.get(CORPORATE_ACTIONS.format(sym=quote(sym)))
            _save_json(cache_dir(data_dir, "nse_api", "corporate_actions") / f"{sym}.json", r.json())
            return f"{len(r.json())} corporate actions"
        step(f"corporate actions {sym}", actions)

    step("bhavcopy", lambda: _bhavcopies(client, data_dir, portfolio, now))

    # Enrichment inputs for filings in the window: XBRL for results, PDFs for people.
    since = now - timedelta(days=days)
    window = [r for r in archive.rows() if r["item"].get("symbol") in symbols and r["published"]
              and datetime.fromisoformat(r["published"]) >= since]
    result_syms = sorted({r["item"]["symbol"] for r in window if cls.classify(r["item"]).category == "results"})
    for sym in result_syms:
        step(f"results XBRL {sym}", lambda sym=sym: _xbrl(client, data_dir, sym, window))
    people = [r for r in window if cls.classify(r["item"]).category == "management_change"]
    step("management-change PDFs", lambda: _pdfs(client, data_dir, people))
    return report


def _bhavcopies(client, data_dir, portfolio, now):
    need = portfolio["thresholds"]["volume_lookback_sessions"] + 8
    folder = cache_dir(data_dir, "bhavcopy")
    got, fetched = 0, 0
    published_today = now.hour * 60 + now.minute >= 16 * 60 + 45   # NSE publishes ~16:33 IST
    for day in prices.previous_weekdays(now.date(), need + 15):
        if got >= need:
            break
        if day == now.date() and not published_today:
            continue
        path = folder / Path(prices.url_for(day)).name
        if path.exists():
            got += 1
            continue
        try:
            r = client.get(prices.url_for(day))
        except FetchError as e:
            if e.status == 404:
                continue          # a holiday, or today's file is not out yet
            raise
        path.write_bytes(r.content)
        got, fetched = got + 1, fetched + 1
    return f"{got} sessions cached ({fetched} downloaded)"


def _xbrl(client, data_dir, sym, window):
    r = client.get(INTEGRATED.format(sym=quote(sym)))
    listing = r.json().get("data", [])
    _save_json(cache_dir(data_dir, "nse_api", "integrated_filings") / f"{sym}.json", listing)
    anchors = [rec for rec in window if rec["item"]["symbol"] == sym
               and cls.classify(rec["item"]).category == "results"]
    downloaded = 0
    for rec in anchors:
        picked = results.pick_filings(listing, parse_exchange_time(rec["item"]["sort_date"]))
        if not picked:
            continue
        for row in (picked["current"], picked["previous"], picked["year_ago"]):
            if row is None:
                continue
            path = cache_dir(data_dir, "xbrl") / Path(row["xbrl"]).name
            if not path.exists():
                path.write_bytes(client.get(row["xbrl"]).content)
                downloaded += 1
    return f"{len(listing)} listed, {downloaded} XBRL files downloaded"


def _pdfs(client, data_dir, records):
    done = 0
    for rec in records:
        url = rec["item"].get("attchmntFile") or ""
        if not url.lower().endswith(".pdf"):
            continue
        out = pdf_text_path(data_dir, url)
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        blob = client.get(url).content
        (cache_dir(data_dir, "pdf") / Path(url).name).write_bytes(blob)
        reader = pypdf.PdfReader(io.BytesIO(blob))
        pages = [(p.extract_text() or "") for p in reader.pages[:PDF_PAGES]]
        _save_json(out, {"url": url, "pages": pages})
        done += 1
    return f"{len(records)} filings, {done} PDFs read"
