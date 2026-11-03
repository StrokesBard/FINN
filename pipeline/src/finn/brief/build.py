"""Build the Brief for one time window: ranked, grouped, enriched, explained.

Pure: reads only local files (the filing archive and data/cache, both written
by `finn collect`), never the network, so the same inputs always produce the
same screen. Every number in the output is copied from a source file or
computed from copied numbers, and carries the URL it came from.
"""
import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from finn.archive import Archive
from finn.brief import classify as cls
from finn.brief import prices, profile, results
from finn.brief.collect import pdf_text_path
from finn.llm import engine, ledger
from finn.llm import tasks as llm_tasks
from finn.llm.config import TIERS as MODEL_TIERS
from finn.llm.config import load_settings
from finn.sources import nse_announcements
from finn.times import IST

WINDOWS = {"24h": ("Last 24 hours", 24), "3d": ("Last 3 days", 72), "7d": ("Last 7 days", 168)}
TIERS = [cls.NEEDS_YOU, cls.WORTH_KNOWING, cls.ROUTINE]
TIER_LABELS = {cls.NEEDS_YOU: "Needs you", cls.WORTH_KNOWING: "Worth knowing", cls.ROUTINE: "Routine"}
TIER_RULES = {
    cls.NEEDS_YOU: "Material by default: results, unusual moves, top-level people changes, M&A, "
                   "litigation, fund raises, pledging, rating downgrades.",
    cls.WORTH_KNOWING: "Useful but not urgent: orders, dividends, transcripts, smaller people changes, "
                       "and anything no rule recognised.",
    cls.ROUTINE: "Compliance paperwork and meeting notices. Hidden, but listed at the bottom.",
}
ORDER = ["results", "price_move"] + [c for c in cls.PRIORITY if c != "results"]
LABELS = {**cls.LABELS, "price_move": "Unusual move"}

BOILERPLATE = re.compile(r"^.*?\bhas (?:informed|submitted to) the Exchange,?\s*(?:about|regarding|that)?\s*", re.I)


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def headline(item):
    """NSE's one-line summary without the "<Company> has informed the Exchange about" preamble."""
    text = " ".join((item.get("attchmntText") or "").split())
    m = BOILERPLATE.match(text)
    if m and m.end() < len(text):
        text = text[m.end():]
    text = text.strip().rstrip(".").strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"":   # only a fully quoted summary loses its quotes
        text = text[1:-1].strip()
    return (text[:1].upper() + text[1:]) if text else (item.get("desc") or "").strip()


PERIOD_ENDED = re.compile(r"(?:period|quarter|half[- ]year|year) ended\s+(?:on\s+)?"
                          r"([A-Z][a-z]+ \d{1,2},? \d{4}|\d{1,2}(?:st|nd|rd|th)? [A-Z][a-z]+,? \d{4})")


def _quarter_from_text(summary):
    """"Q2 FY27" from NSE's "...for the period ended September 30, 2026", if it names a quarter end."""
    m = PERIOD_ENDED.search(summary or "")
    if not m:
        return None
    text = re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(1)).replace(",", "")
    for fmt in ("%B %d %Y", "%d %B %Y", "%b %d %Y", "%d %b %Y"):
        try:
            day = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return results.fy_quarter_label(day) if (day.month, day.day) in ((3, 31), (6, 30), (9, 30), (12, 31)) else None
    return None


def _names(data_dir):
    path = Path(data_dir, "cache", "nse", "EQUITY_L.csv")
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        rows = csv.reader(fh)
        next(rows, None)
        return {r[0].strip(): r[1].strip() for r in rows if len(r) > 1}


def _load_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _filing(rec, classification):
    item = rec["item"]
    url = (item.get("attchmntFile") or "").strip()
    return {
        "id": rec["key"],
        "time": rec["published"],
        "subject": " ".join((item.get("desc") or "").split()),
        "headline": headline(item),
        "nse_summary": " ".join((item.get("attchmntText") or "").split()),
        "url": url if url.startswith("http") else None,
        "size": item.get("attFileSize") or None,
        "category": classification.category,
        "tier": classification.tier,
        "reason": classification.reason,
        "evidence": classification.evidence,
    }


def _classify(data_dir, rec):
    """Rules first; a management change the summary under-describes is checked against the PDF."""
    c = cls.classify(rec["item"])
    if c.category == "management_change" and c.tier != cls.NEEDS_YOU:
        doc = _load_json(pdf_text_path(data_dir, rec["item"].get("attchmntFile") or "x"))
        phrase = profile.top_role(doc["pages"]) if doc else None
        if phrase:
            c = cls.Classification(c.category, cls.NEEDS_YOU, "A change at the top, named in the filing itself.",
                                   f'Filing text: "{phrase}"')
    return c


def _results_enrichment(data_dir, symbol, filings):
    listing = _load_json(Path(data_dir, "cache", "nse_api", "integrated_filings", f"{symbol}.json"))
    if listing is None:
        return {"status": "unavailable", "reason": "NSE's structured-results listing was not fetched."}
    anchor = min(filings, key=lambda f: f["time"])
    picked = results.pick_filings(listing, datetime.fromisoformat(anchor["time"]))
    if not picked or not picked["current"]:
        return {"status": "pending",
                "reason": "NSE has not published the structured (XBRL) copy of these results yet. "
                          "The results PDF is linked below."}
    qe = picked["quarter_end"]
    periods = {"current": (picked["current"], qe), "previous": (picked["previous"], results.quarter_back(qe, 1)),
               "year_ago": (picked["year_ago"], results.quarter_back(qe, 4))}
    parsed, sources = {}, {}
    for key, (row, q_end) in periods.items():
        if row is None:
            parsed[key] = None
            continue
        blob_path = Path(data_dir, "cache", "xbrl", Path(row["xbrl"]).name)
        parsed[key] = results.quarter(blob_path.read_bytes(), q_end) if blob_path.exists() else None
        sources[key] = {"quarter": results.fy_quarter_label(q_end), "quarter_end": q_end.isoformat(),
                        "xbrl": row["xbrl"], "ixbrl": row.get("ixbrl"), "filed": row.get("broadcast_Date"),
                        "revision": row.get("type_Sub")}
    kind = parsed["current"]["kind"] if parsed["current"] else None
    if kind is None:
        return {"status": "unsupported", "quarter": results.fy_quarter_label(qe), "sources": sources,
                "reason": "This results filing uses an XBRL format FINN does not read yet (for example, "
                          "insurance). Open the filing below."}

    def val(period, key):
        q = parsed.get(period)
        if not q or q["kind"] != kind:
            return None
        v = q["values"].get(key)
        return v["value"] if v else None

    metrics = []
    for key, label, terms in results.METRICS[kind]:
        cur = val("current", key)
        if cur is None:
            continue
        prev, yago = val("previous", key), val("year_ago", key)
        inputs = parsed["current"]["values"][key]["inputs"]
        metrics.append({
            "key": key, "label": label, "value": cur, "previous": prev, "year_ago": yago,
            "qoq_pct": results.change_pct(cur, prev), "yoy_pct": results.change_pct(cur, yago),
            "computed": len(terms) > 1,
            "inputs": [{"sign": s, "element": e, "value": v} for s, e, v in inputs],
        })
    missing = [p for p in ("previous", "year_ago") if parsed.get(p) is None]
    return {"status": "ok", "kind": kind, "basis": picked["basis"], "quarter": results.fy_quarter_label(qe),
            "quarter_end": qe.isoformat(), "unit": "INR", "note": results.KIND_NOTE[kind],
            "metrics": metrics, "sources": sources,
            "gaps": [f"No structured filing for the {'previous' if p == 'previous' else 'year-ago'} quarter "
                     "in NSE's integrated-filing listing." for p in missing]}


def _profile_enrichment(data_dir, filings):
    for f in filings:
        if not f["url"]:
            continue
        doc = _load_json(pdf_text_path(data_dir, f["url"]))
        found = profile.extract(doc["pages"], profile.named_person(f["nse_summary"])) if doc else None
        if found:
            return {"text": found["text"], "page": found["page"], "url": f["url"], "filing": f["headline"]}
    return None


def _model_extracts(data_dir, recs):
    """Verified model output for one card's filings, read from the cache only.

    `finn brief` never calls the API. Whatever `finn enrich` stored and verified is
    shown; anything discarded is only counted; filings it has not read yet are counted
    as waiting.
    """
    from finn.llm.enrich import documents
    digest, people, discarded, waiting, seen = None, [], 0, 0, set()
    for task_name, _rec, doc in documents(data_dir, llm_tasks.select(recs, headline)):
        if doc is None:
            continue
        outcome = engine.cached(data_dir, task_name, doc)
        if outcome is None:
            waiting += 1
            continue
        discarded += len(outcome.rejected)
        if not outcome.output:
            continue
        model = MODEL_TIERS[llm_tasks.TASKS[task_name].tier].model
        if task_name == "people_change":
            for c in outcome.output["changes"]:
                key = (llm_tasks.normalize(c["person"]), c["change"])
                if key not in seen:
                    seen.add(key)
                    people.append({**c, "url": doc.url, "model": model})
        elif digest is None:
            digest = {**outcome.output, "url": doc.url, "model": model}
    return digest, people, discarded, waiting


def _price_cards(data_dir, portfolio, names, start, end):
    symbols = set(portfolio["holdings"])
    sessions = prices.load_sessions(Path(data_dir, "cache", "bhavcopy"), symbols)
    t = portfolio["thresholds"]
    checked, cards = [], []
    for idx, s in enumerate(sessions):
        at = prices.session_close(s.day, IST)
        if not (start <= at <= end):
            continue
        checked.append({"day": s.day.isoformat(), "url": s.url, "stocks": len(s.rows)})
        for sym in portfolio["holdings"]:
            actions = _load_json(Path(data_dir, "cache", "nse_api", "corporate_actions", f"{sym}.json"), [])
            m = prices.move_for(sym, idx, sessions, t, actions)
            if not m or not (m.price_hit or m.volume_hit):
                continue
            why = []
            if m.price_hit:
                why.append({"text": f"Closed {m.change_pct:+.1f}% on the day, "
                                    f"beyond your ±{t['price_move_pct']}% threshold.",
                            "evidence": f"NSE bhavcopy {s.day:%d %b %Y}: close {m.close:,.2f} "
                                        f"vs previous close {m.prev_close:,.2f}"})
            if m.volume_hit:
                why.append({"text": f"Traded {m.volume_multiple:.1f}× its average volume of the previous "
                                    f"{len(m.lookback)} sessions, beyond your {t['volume_multiple']}× threshold.",
                            "evidence": f"NSE bhavcopy files {m.lookback[0][0]:%d %b} – {s.day:%d %b %Y}"})
            for w in why:
                w["text"] = f"{s.day:%d %b}: {w['text']}"
            cards.append({
                "id": f"{sym}:price_move:{s.day.isoformat()}", "symbol": sym, "company": names.get(sym, sym),
                "category": "price_move", "category_label": LABELS["price_move"], "tier": cls.NEEDS_YOU,
                "time": at.isoformat(),
                "headline": "Unusual price and volume" if m.price_hit and m.volume_hit
                            else "Unusual price move" if m.price_hit else "Unusual volume",
                "why": why, "filings": [],
                "price": {
                    "day": s.day.isoformat(), "close": m.close, "prev_close": m.prev_close,
                    "change_pct": m.change_pct, "volume": m.volume, "avg_volume": m.avg_volume,
                    "volume_multiple": m.volume_multiple, "source_url": m.source_url,
                    "lookback": [{"day": d.isoformat(), "url": u, "volume": v} for d, u, v in m.lookback],
                    "price_hit": m.price_hit, "volume_hit": m.volume_hit, "caveats": m.caveats,
                },
            })
    return cards, checked


def build(data_dir, portfolio, now, window="24h", settings=None):
    label, hours = WINDOWS[window]
    start = now - timedelta(hours=hours)
    names = _names(data_dir)
    symbols = set(portfolio["holdings"])
    settings = settings or load_settings()

    recs = [r for r in Archive(data_dir, nse_announcements.SOURCE).rows()
            if r["item"].get("symbol") in symbols and r["published"]
            and start <= datetime.fromisoformat(r["published"]) <= now]

    groups, recs_by_group = {}, {}
    for rec in recs:
        c = _classify(data_dir, rec)
        sym = rec["item"]["symbol"]
        groups.setdefault((sym, c.category), []).append(_filing(rec, c))
        recs_by_group.setdefault((sym, c.category), []).append(rec)

    model_totals = {"read": 0, "waiting": 0, "shown": 0, "discarded": 0}
    cards = []
    for (sym, category), filings in groups.items():
        filings.sort(key=lambda f: f["time"], reverse=True)
        lead = min(filings, key=lambda f: (TIERS.index(f["tier"]), f["time"]))   # strongest, then earliest
        tier = lead["tier"]
        company = names.get(sym) or sym
        why = [{"text": lead["reason"], "evidence": lead["evidence"]}]
        if len(filings) > 1:
            why.append({"text": f"{len(filings)} filings from {sym} about {LABELS[category].lower()} "
                                "in this window are grouped into one card.", "evidence": None})
        # The card is dated by its lead filing (e.g. the results announcement, not the deck filed later).
        card = {"id": f"{sym}:{category}:{lead['id']}", "symbol": sym, "company": company,
                "category": category, "category_label": LABELS[category], "tier": tier,
                "time": lead["time"], "headline": lead["headline"], "why": why, "filings": filings}
        if category == "results" and tier != cls.ROUTINE:
            card["results"] = _results_enrichment(data_dir, sym, filings)
            quarter = card["results"].get("quarter") or _quarter_from_text(lead["nse_summary"])
            if quarter:
                card["headline"] = f"{quarter} results"
        if category == "management_change" and tier != cls.ROUTINE:
            card["profile"] = _profile_enrichment(data_dir, filings)

        digest, people, discarded, waiting = _model_extracts(data_dir, recs_by_group[(sym, category)])
        model_totals["waiting"] += waiting
        model_totals["discarded"] += discarded
        if digest or people or discarded:
            model_totals["read"] += 1
            model_totals["shown"] += len(people) + (1 + len(digest["facts"]) if digest else 0)
            card["ai"] = {"digest": digest, "people": people, "discarded": discarded}
        # The model finds the role; the same top-role rule decides, on the verified quote.
        top = next((p for p in people if p["top_role"]), None)
        if top and card["tier"] != cls.NEEDS_YOU:
            card["tier"] = cls.NEEDS_YOU
            card["why"].insert(0, {"text": "A change at the top. The model found the role in the filing; its quote "
                                           "was checked against the PDF and the top-role rule matched it.",
                                   "evidence": f'Filing text: "{top["quote"]}"'})
        cards.append(card)

    # Moves by a company that already has a "needs you" card go inside that card, so one
    # company's news reads as one story. Otherwise all its moves share one card of their own.
    price_cards, checked = _price_cards(data_dir, portfolio, names, start, now)
    by_symbol = {}
    for pc in price_cards:
        by_symbol.setdefault(pc["symbol"], []).append(pc)
    for sym, pcs in by_symbol.items():
        host = min((c for c in cards if c["symbol"] == sym and c["tier"] == cls.NEEDS_YOU),
                   key=lambda c: ORDER.index(c["category"]), default=None)
        if host is not None:
            host["moves"] = [pc["price"] for pc in pcs]
            for pc in pcs:
                host["why"].append({"text": "The stock also crossed a threshold. "
                                            + " ".join(w["text"] for w in pc["why"]),
                                    "evidence": pc["why"][0]["evidence"]})
            continue
        latest = pcs[-1]
        card = {k: v for k, v in latest.items() if k != "price"}
        card["moves"] = [pc["price"] for pc in pcs]
        card["why"] = [w for pc in pcs for w in pc["why"]]
        cards.append(card)
    hits = len(price_cards)
    in_brief = {}
    for c in cards:
        if c["tier"] != cls.ROUTINE:
            in_brief.setdefault(c["symbol"], []).append(c["category_label"])
    for c in cards:
        others = [lab for lab in in_brief.get(c["symbol"], []) if lab != c["category_label"]]
        c["related"] = others

    cards.sort(key=lambda c: (TIERS.index(c["tier"]), ORDER.index(c["category"]),
                              -datetime.fromisoformat(c["time"]).timestamp()))
    for tier in TIERS:
        in_tier = [c for c in cards if c["tier"] == tier]
        for i, c in enumerate(in_tier, 1):
            c["rank"] = i
            c["rank_reason"] = (f"{_ordinal(i)} of {len(in_tier)} in {TIER_LABELS[tier]}. Cards sort by category "
                                f"({c['category_label']} is {_ordinal(ORDER.index(c['category']) + 1)} in the order), "
                                "then newest first.")

    shown = [c for c in cards if c["tier"] != cls.ROUTINE]
    routine = [f for c in cards if c["tier"] == cls.ROUTINE for f in c["filings"]]
    for c in cards:
        if c["tier"] == cls.ROUTINE:
            for f in c["filings"]:
                f["symbol"] = c["symbol"]
    receipt = {}
    for f in routine:
        g = receipt.setdefault(f["category"], {"label": LABELS[f["category"]], "reason": f["reason"], "items": []})
        g["items"].append(f)
    groups_out = sorted(receipt.values(), key=lambda g: -len(g["items"]))
    for g in groups_out:
        g["count"] = len(g["items"])
        g["items"].sort(key=lambda f: f["time"], reverse=True)

    return {
        "generated_at": now.isoformat(),
        "window": {"key": window, "label": label, "start": start.isoformat(), "end": now.isoformat()},
        "windows": [{"key": k, "label": v[0]} for k, v in WINDOWS.items()],
        "portfolio": {"name": portfolio.get("name"), "note": portfolio.get("note"),
                      "holdings": [{"symbol": s, "name": names.get(s, s)} for s in portfolio["holdings"]]},
        "thresholds": portfolio["thresholds"],
        "counts": {"needs_you": sum(c["tier"] == cls.NEEDS_YOU for c in cards),
                   "worth_knowing": sum(c["tier"] == cls.WORTH_KNOWING for c in cards),
                   "routine_filings": len(routine), "filings": len(recs),
                   "companies": len({r["item"]["symbol"] for r in recs})},
        "cards": shown,
        "routine": {"count": len(routine), "groups": groups_out},
        "price_check": {"sessions": checked, "stocks": len(symbols), "hits": hits},
        "ranking": {"tiers": [{"key": t, "label": TIER_LABELS[t], "rule": TIER_RULES[t]} for t in TIERS],
                    "category_order": [LABELS[c] for c in ORDER]},
        "llm": {
            "enabled": settings.enabled, "reason": settings.reason,
            "routing": [
                {"tier": "extract", "model": MODEL_TIERS["extract"].model,
                 "use": "Reads filing PDFs: what a filing with an empty NSE summary discloses, and who changed "
                        "which role, when and why."},
                {"tier": "reason", "model": MODEL_TIERS["reason"].model,
                 "use": "Not used by the Brief. Reserved for weighing management's guidance against reported "
                        "results in the Dossier."},
            ],
            "cards_with_extracts": model_totals["read"], "filings_waiting": model_totals["waiting"],
            "claims_shown": model_totals["shown"], "claims_discarded": model_totals["discarded"],
            "spend": ledger.summary(data_dir),
        },
        "sources": [
            {"label": "NSE corporate announcements", "url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
            {"label": "NSE daily bhavcopy (UDiFF)", "url": "https://www.nseindia.com/all-reports"},
            {"label": "NSE integrated filings (XBRL)", "url": "https://www.nseindia.com/companies-listing/corporate-integrated-filing"},
        ],
    }
