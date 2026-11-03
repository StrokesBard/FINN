import json
import re
from datetime import date, datetime

import pytest
from conftest import FIXTURES

from finn.brief import results
from finn.times import IST

XBRL = FIXTURES / "brief" / "xbrl"


def listing(sym):
    return json.loads((FIXTURES / "brief" / "integrated_filings" / f"{sym}.json").read_text(encoding="utf-8"))


def blob(row):
    return (XBRL / row["xbrl"].rsplit("/", 1)[1]).read_bytes()


def raw_fact(xml, element, quarter_end):
    """Independent check: find the fact by regex over the file text, not with our parser."""
    text = xml.decode("utf-8")
    ctx_ids = [m.group(1) for m in re.finditer(
        r'<xbrli:context id="([^"]+)">(?:(?!</xbrli:context>).)*?<xbrli:endDate>' + quarter_end.isoformat()
        + r'</xbrli:endDate>(?:(?!</xbrli:context>).)*?</xbrli:context>', text, re.S)
        if "explicitMember" not in m.group(0)]
    for cid in ctx_ids:
        m = re.search(r'<[\w-]+:' + element + r'\b[^>]*contextRef="' + re.escape(cid) + r'"[^>]*>([^<]+)<', text)
        if m:
            return float(m.group(1))
    return None


# MEDANTA's results announcement went out at 16:06:37 IST on 3 Nov 2026; SBIN's at 13:47.
@pytest.mark.parametrize("sym, filed", [("MEDANTA", datetime(2026, 11, 3, 16, 6, 37, tzinfo=IST)),
                                        ("SBIN", datetime(2026, 11, 3, 13, 47, 3, tzinfo=IST))])
def test_the_announcement_is_matched_to_its_quarter_and_the_two_comparison_quarters(sym, filed):
    picked = results.pick_filings(listing(sym), filed)
    assert picked["quarter_end"] == date(2026, 9, 30)
    assert picked["basis"] == "Consolidated"
    assert results.parse_qe(picked["previous"]["qe_Date"]) == date(2026, 6, 30)
    assert results.parse_qe(picked["year_ago"]["qe_Date"]) == date(2025, 9, 30)
    assert {picked[k]["consolidated"] for k in ("current", "previous", "year_ago")} == {"Consolidated"}


def test_no_structured_filing_yet_means_pending_not_a_guess():
    # BAJAJFINSV announced results at 12:48 on 3 Nov; NSE had no Sep-2026 XBRL by the evening.
    assert results.pick_filings(listing("BAJAJFINSV"), datetime(2026, 11, 3, 12, 48, tzinfo=IST)) is None


def test_corporate_figures_are_the_reported_facts_and_ebitda_follows_its_formula():
    picked = results.pick_filings(listing("MEDANTA"), datetime(2026, 11, 3, 16, 6, 37, tzinfo=IST))
    xml = blob(picked["current"])
    q = results.quarter(xml, date(2026, 9, 30))
    assert q["kind"] == "corporate"
    v = q["values"]
    reported = [("revenue", "RevenueFromOperations"), ("pbt", "ProfitBeforeTax"), ("pat", "ProfitLossForPeriod")]
    for key, element in reported:
        assert v[key]["value"] == raw_fact(xml, element, date(2026, 9, 30))
    parts = {e: val for _, e, val in v["ebitda"]["inputs"]}
    assert v["ebitda"]["value"] == pytest.approx(parts["ProfitBeforeTax"] + parts["FinanceCosts"]
                                                 + parts["DepreciationDepletionAndAmortisationExpense"]
                                                 - parts["OtherIncome"])
    assert round(v["revenue"]["value"] / 1e7, 1) == 1469.0   # Rs crore, as in Global Health's Q2 FY27 filing


def test_banks_get_bank_metrics_not_ebitda():
    picked = results.pick_filings(listing("SBIN"), datetime(2026, 11, 3, 13, 47, 3, tzinfo=IST))
    xml = blob(picked["current"])
    q = results.quarter(xml, date(2026, 9, 30))
    assert q["kind"] == "bank"
    assert set(q["values"]) == {"nii", "ppop", "pbt", "pat"}
    nii = {e: val for _, e, val in q["values"]["nii"]["inputs"]}
    assert q["values"]["nii"]["value"] == nii["InterestEarned"] - nii["InterestExpended"]
    assert nii["InterestEarned"] == raw_fact(xml, "InterestEarned", date(2026, 9, 30))


@pytest.mark.parametrize("now, then, expected",
                         [(110, 100, 10.0), (90, 100, -10.0), (5, -3, None), (5, 0, None), (5, None, None)])
def test_change_is_not_computed_from_a_loss_or_a_missing_base(now, then, expected):
    got = results.change_pct(now, then)
    assert got == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("qe, label", [(date(2026, 6, 30), "Q1 FY27"), (date(2026, 9, 30), "Q2 FY27"),
                                       (date(2026, 12, 31), "Q3 FY27"), (date(2027, 3, 31), "Q4 FY27")])
def test_indian_fiscal_quarter_labels(qe, label):
    assert results.fy_quarter_label(qe) == label


def test_quarter_arithmetic_crosses_year_ends():
    assert results.quarter_back(date(2026, 3, 31), 1) == date(2025, 12, 31)
    assert results.quarter_back(date(2026, 3, 31), 4) == date(2025, 3, 31)
    assert results.quarter_back(date(2026, 9, 30), 4) == date(2025, 9, 30)
