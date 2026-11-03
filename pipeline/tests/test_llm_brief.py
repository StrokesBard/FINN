"""What the Brief shows from the model: verified claims only, labelled, costed, and nothing without a key."""
import json
from datetime import datetime

import pytest
from conftest import FakeAnthropic, build_data_dir, model_reply

from finn import cli
from finn.brief.build import build
from finn.llm import engine
from finn.llm.config import Settings
from finn.llm.enrich import candidates, documents
from finn.times import IST

NOW = datetime(2026, 11, 3, 17, 5, tzinfo=IST)
PORTFOLIO = {"name": "test", "holdings": ["KEC", "SBIN", "MEDANTA", "RELIANCE", "ALKEM", "BAJAJFINSV", "UPL", "ITC"],
             "thresholds": {"price_move_pct": 5, "volume_multiple": 2, "volume_lookback_sessions": 20}}
KEY = "sk-ant-test-0000-not-a-real-key"
ON = Settings(True, "API key found in the environment.", "environment", KEY)
OFF = Settings(False, "No API key: ANTHROPIC_API_KEY is not set in the environment or in .env.")


def card(brief, symbol, category):
    return next(c for c in brief["cards"] if c["symbol"] == symbol and c["category"] == category)


@pytest.fixture
def data_dir(tmp_path):
    return build_data_dir(tmp_path)


def test_without_a_key_the_brief_builds_and_says_so(data_dir):
    b = build(data_dir, PORTFOLIO, NOW, "24h", settings=OFF)
    assert b["llm"]["enabled"] is False and "ANTHROPIC_API_KEY" in b["llm"]["reason"]
    assert b["llm"]["filings_waiting"] > 0 and b["llm"]["spend"]["calls"] == 0
    assert not any("ai" in c for c in b["cards"])


def test_routing_is_stated_on_the_page(data_dir):
    routing = build(data_dir, PORTFOLIO, NOW, "24h", settings=OFF)["llm"]["routing"]
    assert [(r["tier"], r["model"]) for r in routing] == [("extract", "claude-haiku-5-5"),
                                                          ("reason", "claude-opus-5-5")]
    assert routing[1]["use"].startswith("Not used by the Brief")


def test_enrich_without_a_key_makes_no_calls_and_exits_cleanly(data_dir, capsys, monkeypatch):
    monkeypatch.setattr(cli, "now_ist", lambda: NOW)
    args = type("A", (), {"data_dir": data_dir, "portfolio": None})()
    monkeypatch.setattr("finn.brief.collect.load_portfolio", lambda _: PORTFOLIO)
    assert cli._enrich(args, settings=OFF, client=FakeAnthropic()) == 0
    out = capsys.readouterr().out
    assert "Model extraction is off" in out and "wait until a key is set" in out


def test_only_verified_claims_reach_the_card_and_the_key_is_never_printed(data_dir, capsys, monkeypatch):
    # The ALKEM CEO letter: one true claim (quoted from the real PDF) and one the filing does not support.
    _, rec, alkem = next((t, r, d) for t, r, d in documents(data_dir, candidates(data_dir, PORTFOLIO, NOW, 1))
                         if r["item"]["symbol"] == "ALKEM")
    page = " ".join(alkem.pages[0].split())
    quote = page[page.index("has appointed Dr. Amrut Naik as the Chief Executive Officer"):][:120]
    answer = {"changes": [
        {"person": "Dr. Amrut Naik", "role": "Chief Executive Officer", "change": "appointed",
         "effective_date": None, "reason": None, "quote": quote},
        {"person": "Dr. Amrut Naik", "role": "Managing Director", "change": "appointed",
         "effective_date": None, "reason": None, "quote": quote},
    ]}
    replies = {"people_change:ALKEM": model_reply(answer)}

    class Routed(FakeAnthropic):
        """Answers ALKEM with the case above and every other filing with nothing."""
        def __init__(self):
            super().__init__()
            outer = self

            def create(**request):
                outer.messages.calls.append(request)
                if "Alkem" in request["messages"][0]["content"]:
                    return replies["people_change:ALKEM"]
                return model_reply({"changes": []} if "List every change" in request["messages"][0]["content"]
                                   else {"headline": "", "headline_quote": "", "facts": []})
            self.messages.create = create

    monkeypatch.setattr(cli, "now_ist", lambda: NOW)
    monkeypatch.setattr("finn.brief.collect.load_portfolio", lambda _: PORTFOLIO)
    args = type("A", (), {"data_dir": data_dir, "portfolio": None})()
    assert cli._enrich(args, settings=ON, client=Routed()) == 0
    printed = capsys.readouterr().out
    assert KEY not in printed and "claims shown" in printed and "$" in printed

    b = build(data_dir, PORTFOLIO, NOW, "24h", settings=OFF)   # key gone again: cached, verified output stays
    ai = card(b, "ALKEM", "management_change")["ai"]
    assert [(p["role"], p["top_role"]) for p in ai["people"]] == [("Chief Executive Officer", True)]
    assert ai["discarded"] == 1 and ai["people"][0]["model"] == "claude-haiku-5-5"
    assert ai["people"][0]["quote"] == quote and ai["people"][0]["page"] == 1
    assert b["llm"]["spend"]["calls"] >= 1 and b["llm"]["claims_discarded"] >= 1
    on_disk = json.loads(next((data_dir / "cache" / "llm" / "people_change").glob("*.json")).read_text("utf-8"))
    assert KEY not in json.dumps(on_disk)


def test_a_quoted_top_role_escalates_a_card_the_rules_left_in_worth_knowing(data_dir):
    # KEC's appointee "is the Vice Chairman of RPG Enterprises": the words exist, but no
    # appointment as Vice Chairman is stated, so the card must stay where the rules put it.
    _, _, kec = next((t, r, d) for t, r, d in documents(data_dir, candidates(data_dir, PORTFOLIO, NOW, 1))
                     if r["item"]["symbol"] == "KEC")
    page = " ".join(kec.pages[1].split())
    misread = page[page.index("Mr. Anant Vardhan Goenka is the Vice Chairman"):][:70]
    engine.run(data_dir, "people_change", kec, ON, FakeAnthropic(model_reply({"changes": [
        {"person": "Mr. Anant Vardhan Goenka", "role": "Vice Chairman", "change": "appointed",
         "effective_date": None, "reason": None, "quote": misread}]})))
    b = build(data_dir, PORTFOLIO, NOW, "24h", settings=OFF)
    kec_card = card(b, "KEC", "management_change")
    assert kec_card["tier"] == "worth_knowing"
    assert kec_card["ai"]["people"] == [] and kec_card["ai"]["discarded"] == 1
