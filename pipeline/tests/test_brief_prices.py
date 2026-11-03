import json
from datetime import date

import pytest
from conftest import FIXTURES

from finn.brief import prices

BHAV = FIXTURES / "brief" / "bhavcopy"
SYMBOLS = {"KEC", "SBIN", "MEDANTA", "RELIANCE", "MOLDTKPAC", "JSWDULUX"}
T = {"price_move_pct": 5, "volume_multiple": 2, "volume_lookback_sessions": 20}


@pytest.fixture(scope="module")
def sessions():
    return prices.load_sessions(BHAV, SYMBOLS)


def actions(sym):
    return json.loads((FIXTURES / "brief" / "corporate_actions" / f"{sym}.json").read_text())


def idx(sessions, day):
    return next(i for i, s in enumerate(sessions) if s.day == day)


def test_sessions_load_in_date_order_with_their_source_urls(sessions):
    days = [s.day for s in sessions]
    assert days == sorted(days) and len(days) >= 21
    assert all(s.url.endswith(f"_{s.day:%Y%m%d}_F_0000.csv.zip") for s in sessions)


def test_move_is_nse_close_against_nse_previous_close(sessions):
    i = idx(sessions, date(2026, 11, 3))
    row = sessions[i].rows["KEC"]
    m = prices.move_for("KEC", i, sessions, T, actions("KEC"))
    assert m.close == float(row["ClsPric"]) and m.prev_close == float(row["PrvsClsgPric"])
    assert m.change_pct == pytest.approx((m.close / m.prev_close - 1) * 100)
    assert m.price_hit                                   # KEC closed down more than 5% on 3 Nov


def test_volume_is_compared_with_the_previous_twenty_sessions_files(sessions):
    i = idx(sessions, date(2026, 11, 3))
    m = prices.move_for("KEC", i, sessions, T, actions("KEC"))
    prior = [int(float(s.rows["KEC"]["TtlTradgVol"])) for s in sessions[:i] if "KEC" in s.rows][-20:]
    assert [v for _, _, v in m.lookback] == prior
    assert m.avg_volume == pytest.approx(sum(prior) / 20)
    assert m.volume_multiple == pytest.approx(m.volume / (sum(prior) / 20))
    assert all(u.startswith("https://nsearchives.nseindia.com/") for _, u, _ in m.lookback)
    assert m.volume_hit


@pytest.mark.parametrize("sym, ex", [("MOLDTKPAC", "09 Oct 2026"), ("JSWDULUX", "22 Oct 2026")])
def test_a_bonus_or_split_in_the_lookback_stops_the_volume_comparison(sessions, sym, ex):
    # Real corporate actions: MOLDTKPAC 1:1 bonus, JSWDULUX face-value split.
    i = idx(sessions, date(2026, 11, 3))
    m = prices.move_for(sym, i, sessions, T, actions(sym))
    assert m.avg_volume is None and not m.volume_hit
    assert any(ex in c for c in m.caveats)


def test_too_little_history_is_said_not_hidden(sessions):
    m = prices.move_for("KEC", 3, sessions, T, actions("KEC"))
    assert m.avg_volume is None and "fewer than the 20" in m.caveats[0]


def test_a_stock_that_did_not_trade_has_no_move(sessions):
    assert prices.move_for("NOTASTOCK", len(sessions) - 1, sessions, T) is None
