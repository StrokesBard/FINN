"""Calling, caching, cost logging and failure handling, with a stand-in client (no key, no network)."""
import json

import pytest
from conftest import FakeAnthropic, api_error, model_reply
from test_llm_tasks import GOOD_DIGEST, ITC

from finn.llm import engine, ledger
from finn.llm.config import TIERS, Settings
from finn.llm.tasks import TASKS, Task

KEY = "sk-ant-test-0000-not-a-real-key"
ON = Settings(True, "API key found in the environment.", "environment", KEY)
OFF = Settings(False, "No API key: ANTHROPIC_API_KEY is not set in the environment or in .env.")


def usage_rows(data_dir):
    p = ledger.path(data_dir)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_a_verified_answer_is_cached_and_costed_and_never_requested_twice(tmp_path):
    client = FakeAnthropic(model_reply(GOOD_DIGEST, input_tokens=2400, output_tokens=350))
    first = engine.run(tmp_path, "filing_digest", ITC, ON, client)
    assert first.status == "verified" and not first.cached
    assert first.cost_usd == pytest.approx((2400 * 0.10 + 350 * 0.50) / 1e6)

    request = client.calls[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"]["effort"] == "low"
    assert request["output_config"]["format"] == {"type": "json_schema", "schema": TASKS["filing_digest"].schema}

    again = engine.run(tmp_path, "filing_digest", ITC, ON, client)
    assert again.cached and again.output == first.output
    assert len(client.calls) == 1 and len(usage_rows(tmp_path)) == 1


def test_no_key_means_no_call_and_a_clear_status(tmp_path):
    client = FakeAnthropic()
    out = engine.run(tmp_path, "filing_digest", ITC, OFF, client)
    assert out.status == "disabled" and "ANTHROPIC_API_KEY" in out.detail
    assert client.calls == [] and not (tmp_path / "cache").exists() and usage_rows(tmp_path) == []


def test_cached_results_still_show_after_the_key_is_removed(tmp_path):
    engine.run(tmp_path, "filing_digest", ITC, ON, FakeAnthropic(model_reply(GOOD_DIGEST)))
    out = engine.run(tmp_path, "filing_digest", ITC, OFF, FakeAnthropic())
    assert out.cached and out.status == "verified"


@pytest.mark.parametrize("reply, status", [
    (model_reply("I can't help with that.", stop_reason="refusal"), "refused"),
    (model_reply('{"headline": "cut off', stop_reason="max_tokens"), "truncated"),
    (model_reply("not json at all"), "invalid"),
    (model_reply({"headline": "x", "facts": []}), "invalid"),                          # schema: missing quote
    (model_reply({**GOOD_DIGEST, "headline_quote": "a passage that is nowhere in the filing"}), "rejected"),
])
def test_unusable_answers_show_nothing_but_are_paid_for_and_cached(tmp_path, reply, status):
    out = engine.run(tmp_path, "filing_digest", ITC, ON, FakeAnthropic(reply))
    assert out.status == status and out.output is None
    assert usage_rows(tmp_path)[0]["status"] == status
    assert engine.cached(tmp_path, "filing_digest", ITC).status == status   # not re-sent on the next run


def test_rate_limits_and_outages_are_not_cached_so_the_next_run_retries(tmp_path):
    out = engine.run(tmp_path, "filing_digest", ITC, ON, FakeAnthropic(api_error("RateLimitError", 429)))
    assert out.status == "error" and engine.cached(tmp_path, "filing_digest", ITC) is None


def test_a_rejected_key_stops_the_run_without_echoing_the_key(tmp_path):
    with pytest.raises(engine.KeyRejected) as e:
        engine.run(tmp_path, "filing_digest", ITC, ON, FakeAnthropic(api_error("AuthenticationError", 401)))
    assert "401" in str(e.value) and KEY not in str(e.value)


def test_the_cache_key_changes_with_task_version_and_document(tmp_path, monkeypatch):
    task = TASKS["filing_digest"]
    base = engine.cache_key(task, ITC)
    bumped = Task(task.name, task.version + "x", task.tier, task.schema, task.instructions, task.verify)
    assert engine.cache_key(bumped, ITC) != base
    other = type(ITC)(ITC.url, (ITC.pages[0] + " ",) + ITC.pages[1:], ITC.symbol, ITC.company, ITC.subject, ITC.filed)
    assert engine.cache_key(task, other) != base


def test_the_reasoning_tier_goes_to_opus_with_server_side_fallback(tmp_path, monkeypatch):
    reason_task = Task("probe", "1", "reason", TASKS["filing_digest"].schema, "probe", TASKS["filing_digest"].verify)
    monkeypatch.setitem(TASKS, "probe", reason_task)
    client = FakeAnthropic(model_reply(GOOD_DIGEST))
    engine.run(tmp_path, "probe", ITC, ON, client)
    assert client.messages.calls == []
    request = client.beta.messages.calls[0]
    assert request["model"] == "claude-opus-5-5" and request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]


def test_cost_arithmetic_per_model():
    u = {"input_tokens": 10_000, "output_tokens": 1_000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert ledger.cost_usd(TIERS["extract"], u) == pytest.approx(0.0015)        # Haiku 5.5: $0.10 / $0.50
    assert ledger.cost_usd(TIERS["reason"], u) == pytest.approx(0.06)           # Opus 5.5: $4 / $20
    long = {**u, "input_tokens": 120_000}                                      # over 100K: $0.50 / $2.50
    assert ledger.cost_usd(TIERS["extract"], long) == pytest.approx(0.0625)


def test_the_spend_summary_adds_up(tmp_path):
    for _ in range(3):
        ledger.record(tmp_path, task="filing_digest", tier="extract", doc_url="u", status="verified",
                      usage={"input_tokens": 2000, "output_tokens": 300,
                             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})
    s = ledger.summary(tmp_path)
    assert s["calls"] == 3 and s["cost_usd"] == pytest.approx(3 * (2000 * 0.10 + 300 * 0.50) / 1e6)
    assert s["by_model"]["claude-haiku-5-5"]["input_tokens"] == 6000
