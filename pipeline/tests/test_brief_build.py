"""The whole Brief, built from a real slice of 2-3 Nov 2026 (filings, prices, XBRL, PDFs)."""
from datetime import datetime

import pytest
from conftest import build_data_dir

from finn.brief.build import ORDER, TIERS, build
from finn.llm.config import Settings
from finn.times import IST

NO_KEY = Settings(False, "No API key (test).")
NOW = datetime(2026, 11, 3, 17, 5, tzinfo=IST)
PORTFOLIO = {"name": "test", "holdings": ["KEC", "SBIN", "MEDANTA", "RELIANCE", "ALKEM", "BAJAJFINSV", "UPL", "ITC"],
             "thresholds": {"price_move_pct": 5, "volume_multiple": 2, "volume_lookback_sessions": 20}}


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    return build_data_dir(tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="module")
def brief(data_dir):
    return build(data_dir, PORTFOLIO, NOW, "24h", settings=NO_KEY)


def cards(brief, **match):
    return [c for c in brief["cards"] if all(c.get(k) == v for k, v in match.items())]


def test_every_filing_in_the_window_is_on_a_card_or_in_the_routine_receipt(brief):
    shown = sum(len(c["filings"]) for c in brief["cards"])
    assert shown + brief["routine"]["count"] == brief["counts"]["filings"]
    ids = [f["id"] for c in brief["cards"] for f in c["filings"]] + \
          [f["id"] for g in brief["routine"]["groups"] for f in g["items"]]
    assert len(ids) == len(set(ids))   # and none twice


def test_order_is_tier_then_category_then_newest(brief):
    key = [(TIERS.index(c["tier"]), ORDER.index(c["category"]), -datetime.fromisoformat(c["time"]).timestamp())
           for c in brief["cards"]]
    assert key == sorted(key)
    for tier in ("needs_you", "worth_knowing"):
        assert [c["rank"] for c in cards(brief, tier=tier)] == list(range(1, len(cards(brief, tier=tier)) + 1))


def test_every_card_explains_its_place(brief):
    for c in brief["cards"]:
        assert c["why"] and all(w["text"] for w in c["why"]), c["id"]
        assert c["rank_reason"].startswith(f"{c['rank']}")


def test_results_cards_carry_traceable_numbers(brief):
    medanta = cards(brief, symbol="MEDANTA", category="results")[0]
    r = medanta["results"]
    assert r["status"] == "ok" and r["quarter"] == "Q2 FY27" and r["basis"] == "Consolidated"
    assert [m["label"] for m in r["metrics"]] == ["Revenue", "EBITDA", "PBT", "PAT"]
    assert {k: s["xbrl"].startswith("https://nsearchives.nseindia.com/") for k, s in r["sources"].items()} == \
           {"current": True, "previous": True, "year_ago": True}
    rev = r["metrics"][0]
    assert rev["qoq_pct"] == pytest.approx((rev["value"] / rev["previous"] - 1) * 100)
    assert rev["yoy_pct"] == pytest.approx((rev["value"] / rev["year_ago"] - 1) * 100)


def test_a_bank_is_shown_with_bank_metrics(brief):
    labels = [m["label"] for m in cards(brief, symbol="SBIN", category="results")[0]["results"]["metrics"]]
    assert labels == ["Net interest income", "Pre-provision profit", "PBT", "PAT"]


def test_results_without_xbrl_say_pending_and_keep_the_quarter_from_nse_text(brief):
    baf = cards(brief, symbol="BAJAJFINSV", category="results")[0]
    assert baf["results"]["status"] == "pending"
    assert baf["headline"] == "Q2 FY27 results"
    itc = cards(brief, symbol="ITC", category="results")[0]
    assert itc["results"]["status"] == "unavailable"   # no listing in this fixture slice


def test_a_move_by_a_company_with_news_folds_into_that_card(brief):
    kec = cards(brief, symbol="KEC", category="results")[0]
    assert kec["moves"][0]["day"] == "2026-11-03" and kec["moves"][0]["price_hit"]
    assert not cards(brief, symbol="KEC", category="price_move")
    assert any("crossed a threshold" in w["text"] for w in kec["why"])


def test_a_move_with_no_other_news_gets_its_own_card_with_sources(brief):
    rel = cards(brief, symbol="RELIANCE", category="price_move")[0]
    assert "price" not in rel and len(rel["moves"]) == 1
    p = rel["moves"][0]
    assert rel["tier"] == "needs_you" and p["volume_hit"]
    assert p["source_url"].endswith("_20261103_F_0000.csv.zip")
    assert len(p["lookback"]) == 20 and all(x["url"] for x in p["lookback"])


def test_several_moves_by_one_company_share_one_card_each_with_its_own_source(data_dir):
    # RELIANCE crossed thresholds on 2 Nov and again on 3 Nov; the 3-day Brief shows one card.
    b = build(data_dir, PORTFOLIO, NOW, "3d", settings=NO_KEY)
    rel = cards(b, symbol="RELIANCE", category="price_move")
    assert len(rel) == 1
    days = [m["day"] for m in rel[0]["moves"]]
    assert days == ["2026-11-02", "2026-11-03"]
    assert [m["source_url"].rsplit("_0_0_0_", 1)[1][:8] for m in rel[0]["moves"]] == ["20261102", "20261103"]
    assert len(rel[0]["why"]) >= 2 and rel[0]["why"][0]["text"].startswith("02 Nov")


def test_a_top_management_change_quotes_the_filings_own_profile(brief):
    alkem = cards(brief, symbol="ALKEM", category="management_change")[0]
    assert alkem["tier"] == "needs_you"
    assert alkem["profile"]["text"].startswith("Dr. Amrut Naik")
    assert alkem["profile"]["url"] == alkem["filings"][0]["url"]


def test_routine_items_are_hidden_but_counted_with_reasons(brief):
    assert not cards(brief, tier="routine")
    for g in brief["routine"]["groups"]:
        assert g["count"] == len(g["items"]) and g["reason"]


def test_windows_contain_what_their_label_says(data_dir):
    for key in ("24h", "3d", "7d"):
        b = build(data_dir, PORTFOLIO, NOW, key, settings=NO_KEY)
        start = datetime.fromisoformat(b["window"]["start"])
        for c in b["cards"]:
            for f in c["filings"]:
                assert start <= datetime.fromisoformat(f["time"]) <= NOW
