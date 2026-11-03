"""`finn enrich`: send the filings rules can't summarise to the model, once each.

Pure bookkeeping around engine.run. With no key it reports what is waiting and
returns; the Brief still builds, and says model extraction is off.
"""
from collections import Counter
from datetime import datetime, timedelta

from finn.archive import Archive
from finn.brief.collect import pdf_text_path
from finn.llm import engine, tasks
from finn.sources import nse_announcements


def window_records(data_dir, portfolio, now, days):
    since = now - timedelta(days=days)
    return [r for r in Archive(data_dir, nse_announcements.SOURCE).rows()
            if r["item"].get("symbol") in portfolio["holdings"] and r["published"]
            and since <= datetime.fromisoformat(r["published"]) <= now]


def candidates(data_dir, portfolio, now, days=7):
    from finn.brief.build import headline
    return tasks.select(window_records(data_dir, portfolio, now, days), headline)


def documents(data_dir, picked):
    """[(task, record, Document | None)]; None when the PDF has not been fetched or has no text layer."""
    out = []
    for task_name, rec in picked:
        path = pdf_text_path(data_dir, rec["item"]["attchmntFile"])
        doc = tasks.document_for(rec["item"], path) if path.exists() else None
        if doc is not None and not any(p.strip() for p in doc.pages):
            doc = None   # a scanned PDF: nothing to quote from, so nothing can be verified
        out.append((task_name, rec, doc))
    return out


def enrich(data_dir, portfolio, now, settings, client=None, days=7):
    report = {"enabled": settings.enabled, "reason": settings.reason, "candidates": 0, "no_text": 0,
              "status": Counter(), "claims_shown": 0, "claims_discarded": 0, "cost_usd": 0.0, "stopped": None}
    picked = documents(data_dir, candidates(data_dir, portfolio, now, days))
    report["candidates"] = len(picked)
    if settings.enabled and client is None:
        client = engine.make_client(settings)
    for task_name, _rec, doc in picked:
        if doc is None:
            report["no_text"] += 1
            continue
        try:
            outcome = engine.run(data_dir, task_name, doc, settings, client)
        except engine.KeyRejected as e:
            report["stopped"] = str(e)
            break
        report["status"][("cached " if outcome.cached else "") + outcome.status] += 1
        report["cost_usd"] += 0.0 if outcome.cached else outcome.cost_usd
        report["claims_discarded"] += len(outcome.rejected)
        if outcome.output:
            people = outcome.output.get("changes", [])
            report["claims_shown"] += len(people) or 1 + len(outcome.output.get("facts", []))
    return report
