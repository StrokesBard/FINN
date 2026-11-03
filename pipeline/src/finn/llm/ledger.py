"""What the model calls cost: one JSON line per API call, summarised for the screen.

    data/llm/usage.jsonl
"""
import json
from datetime import datetime
from pathlib import Path

from finn.llm.config import CACHE_READ_MULTIPLIER, CACHE_WRITE_MULTIPLIER, TIERS
from finn.times import IST


def cost_usd(spec, usage):
    """USD for one call from its usage counts, at the spec's rates (long-context rates when they apply)."""
    prompt = usage["input_tokens"] + usage["cache_read_input_tokens"] + usage["cache_creation_input_tokens"]
    long_ctx = spec.long_context_threshold is not None and prompt > spec.long_context_threshold
    rate_in = spec.long_usd_per_mtok_in if long_ctx else spec.usd_per_mtok_in
    rate_out = spec.long_usd_per_mtok_out if long_ctx else spec.usd_per_mtok_out
    return (usage["input_tokens"] * rate_in
            + usage["cache_creation_input_tokens"] * rate_in * CACHE_WRITE_MULTIPLIER
            + usage["cache_read_input_tokens"] * rate_in * CACHE_READ_MULTIPLIER
            + usage["output_tokens"] * rate_out) / 1_000_000


def usage_dict(usage):
    """The four counts from an SDK Usage object (or a dict), missing ones as 0."""
    get = usage.get if isinstance(usage, dict) else (lambda k, d=0: getattr(usage, k, d))
    return {k: int(get(k, 0) or 0) for k in ("input_tokens", "output_tokens",
                                              "cache_creation_input_tokens", "cache_read_input_tokens")}


def path(data_dir):
    return Path(data_dir) / "llm" / "usage.jsonl"


def record(data_dir, *, task, tier, doc_url, usage, status, request_id=None):
    spec = TIERS[tier]
    row = {"time": datetime.now(IST).isoformat(timespec="seconds"), "task": task, "model": spec.model,
           "doc": doc_url, "status": status, "request_id": request_id, **usage,
           "cost_usd": round(cost_usd(spec, usage), 8)}
    p = path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def summary(data_dir):
    rows = []
    p = path(data_dir)
    if p.exists():
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_model = {}
    for r in rows:
        m = by_model.setdefault(r["model"], {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["input_tokens"] += r["input_tokens"] + r["cache_read_input_tokens"] + r["cache_creation_input_tokens"]
        m["output_tokens"] += r["output_tokens"]
        m["cost_usd"] += r["cost_usd"]
    return {"calls": len(rows), "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
            "since": rows[0]["time"] if rows else None, "by_model": by_model}
