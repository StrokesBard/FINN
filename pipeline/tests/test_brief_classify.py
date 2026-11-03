import json

import pytest
from conftest import FIXTURES

from finn.brief.classify import NEEDS_YOU, ROUTINE, WORTH_KNOWING, classify

# One real filing per rule, picked from a week of NSE announcements (scripts/capture_fixtures.py brief).
CASES = {c["case"]: c["item"] for c in
         json.loads((FIXTURES / "brief" / "classify_cases.json").read_text(encoding="utf-8"))}

EXPECTED = {
    "results_outcome": ("results", NEEDS_YOU),
    "results_press_q": ("results", NEEDS_YOU),          # "Press Release Q2FY27": no word break before FY
    "investor_presentation": ("results", WORTH_KNOWING),
    "integrated_financial": ("results", WORTH_KNOWING),
    "mgmt_top": ("management_change", NEEDS_YOU),
    "mgmt_other": ("management_change", WORTH_KNOWING),
    "change_in_management": ("management_change", WORTH_KNOWING),
    "auditor_change": ("routine_paperwork", ROUTINE),
    "acquisition": ("mna", NEEDS_YOU),
    "litigation": ("litigation", NEEDS_YOU),
    "material_issue": ("material_event", NEEDS_YOU),
    "board_fund_raise": ("fund_raise", NEEDS_YOU),
    "credit_rating": ("credit_rating", WORTH_KNOWING),
    "orders": ("orders_business", WORTH_KNOWING),
    "news_verification": ("clarification", WORTH_KNOWING),
    "transcript": ("earnings_call", WORTH_KNOWING),
    "meeting_schedule": ("investor_meetings", ROUTINE),
    "newspaper": ("routine_paperwork", ROUTINE),
    "rta_update": ("routine_paperwork", ROUTINE),
    "record_date_dividend": ("dividend", WORTH_KNOWING),
    "double_spaced_subject": ("material_event", NEEDS_YOU),  # NSE wrote "Final  forensic  audit  report"
    "general_update_unknown": ("unclassified", WORTH_KNOWING),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_real_filings_land_in_the_expected_category_and_tier(case):
    got = classify(CASES[case])
    assert (got.category, got.tier) == EXPECTED[case]


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_label_comes_with_a_reason_and_the_text_it_matched(case):
    got = classify(CASES[case])
    assert got.reason and got.evidence and got.label
    assert CASES[case]["desc"].split()[0] in got.evidence   # quotes NSE's own subject line


def test_a_top_role_named_in_the_summary_is_quoted_as_evidence():
    got = classify(CASES["mgmt_top"])
    assert "Chief Executive" in got.evidence or "CEO" in got.evidence


def test_unknown_filings_are_shown_not_hidden():
    assert classify(CASES["general_update_unknown"]).tier != ROUTINE
    assert classify({"desc": "Something NSE invents next year", "attchmntText": ""}).tier == WORTH_KNOWING
