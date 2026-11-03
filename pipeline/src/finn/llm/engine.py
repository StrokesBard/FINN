"""Run a task on a document: cache, call, validate, verify, record cost.

Every outcome is cached under a key made of the task, its version, the model and
the exact prompt, so each document is sent at most once. Only the verified part
of an answer is ever handed to the Brief; the raw answer stays in the cache for audit.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from finn.llm import ledger
from finn.llm.config import TIERS
from finn.llm.tasks import SYSTEM, TASKS, schema_errors
from finn.times import IST


class KeyRejected(Exception):
    """The API refused the key (401/403). Raised so a run stops instead of failing every document."""


@dataclass
class Outcome:
    status: str                    # verified | rejected | refused | truncated | invalid | error | disabled | not_run
    output: dict | None = None     # verified claims only
    rejected: list = field(default_factory=list)
    cached: bool = False
    cost_usd: float = 0.0
    detail: str | None = None


def cache_key(task, doc):
    spec = TIERS[task.tier]
    material = json.dumps([task.name, task.version, spec.model, spec.effort, SYSTEM,
                           task.schema, task.prompt(doc)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_path(data_dir, task, doc):
    return Path(data_dir) / "cache" / "llm" / task.name / f"{cache_key(task, doc)}.json"


def cached(data_dir, task_name, doc):
    """The stored outcome for this exact task + document, or None. Never calls the API."""
    task = TASKS[task_name]
    p = cache_path(data_dir, task, doc)
    if not p.exists():
        return None
    row = json.loads(p.read_text(encoding="utf-8"))
    return Outcome(row["status"], row.get("verified"), row.get("rejected", []), True, row.get("cost_usd", 0.0),
                   row.get("detail"))


def make_client(settings):
    import anthropic
    return anthropic.Anthropic(api_key=settings.api_key, max_retries=2, timeout=120.0)


def _call(client, task, doc):
    spec = TIERS[task.tier]
    request = dict(model=spec.model, max_tokens=spec.max_tokens, system=SYSTEM,
                   messages=[{"role": "user", "content": task.prompt(doc)}],
                   output_config={"effort": spec.effort,
                                  "format": {"type": "json_schema", "schema": task.schema}})
    if spec.fallbacks:  # Opus tier: re-run a policy decline on a fallback model inside the same call
        return client.beta.messages.create(**request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    return client.messages.create(**request)


def run(data_dir, task_name, doc, settings, client=None):
    task = TASKS[task_name]
    hit = cached(data_dir, task_name, doc)
    if hit:
        return hit
    if not settings.enabled:
        return Outcome("disabled", detail=settings.reason)

    import anthropic
    client = client or make_client(settings)
    try:
        response = _call(client, task, doc)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise KeyRejected(f"the API rejected the key (HTTP {e.status_code})") from None
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        # Not cached: a rate limit or outage should be retried on the next run.
        return Outcome("error", detail=f"{type(e).__name__}: {getattr(e, 'status_code', '')}".strip(": "))

    usage = ledger.usage_dict(response.usage)
    status, raw, verified, rejected, detail = None, None, None, [], None
    if response.stop_reason == "refusal":
        status, detail = "refused", "the model declined this document"
    elif response.stop_reason == "max_tokens":
        status, detail = "truncated", "the answer hit max_tokens"
    else:
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        try:
            raw = json.loads(text)
        except ValueError:
            status, detail = "invalid", "the answer was not JSON"
        else:
            errors = schema_errors(task.schema, raw)
            if errors:
                status, detail = "invalid", "; ".join(errors[:3])
            else:
                verified, rejected = task.verify(raw, doc)
                status = "verified" if verified else "rejected"
    row = ledger.record(data_dir, task=task.name, tier=task.tier, doc_url=doc.url, usage=usage, status=status,
                        request_id=getattr(response, "_request_id", None))
    p = cache_path(data_dir, task, doc)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "task": task.name, "version": task.version, "model": TIERS[task.tier].model, "doc": doc.url,
        "created": datetime.now(IST).isoformat(timespec="seconds"), "status": status, "detail": detail,
        "verified": verified, "rejected": rejected, "raw": raw, "usage": usage, "cost_usd": row["cost_usd"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return Outcome(status, verified, rejected, False, row["cost_usd"], detail)
