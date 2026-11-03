"""Schemas, verifiers and selection for the two model tasks, on real filings.

The model's answers here are test doubles written for each case; the documents
they are checked against are the real texts the pipeline extracted.
"""
import json

from conftest import FIXTURES

from finn.brief.build import headline
from finn.llm import engine
from finn.llm.tasks import TASKS, document_for, needs_digest, schema_errors, select

LLM = FIXTURES / "llm"
RECORDS = [json.loads(line) for line in (LLM / "announcements.jsonl").read_text(encoding="utf-8").splitlines()]


def doc(name):
    rec = next(r for r in RECORDS if r["item"]["attchmntFile"].endswith(name))
    return document_for(rec["item"], LLM / "pdf_text" / f"{name}.json")


ITC = doc("ITC_02112026184512_SE_Sproutlife_.pdf")
HDFC = doc("HDFCBANK3_31102026221631_SE_INTIMATION-_Sanjay_Dsouza.pdf")
ALKEM = document_for({"symbol": "ALKEM", "sm_name": "Alkem Laboratories Limited"},
                     FIXTURES / "brief" / "pdf_text" / "ALKEM_03112026133322_Reg30_Appointment_of_CEO_signed.pdf.json")

ITC_HEADLINE_QUOTE = ("has approved the Scheme of Amalgamation of Sproutlife Foods Private Limited, "
                      "a wholly owned subsidiary, with the Company")
GOOD_DIGEST = {
    "headline": "ITC's board approved merging its wholly owned subsidiary Sproutlife Foods Private Limited into ITC.",
    "headline_quote": ITC_HEADLINE_QUOTE,
    "facts": [
        {"label": "Effective date", "value": "1st April, 2026",
         "quote": "will take effect from 1st April, 2026"},
        {"label": "Status", "value": "subject to necessary approvals",
         "quote": "The aforesaid Scheme of Amalgamation, which is subject to necessary approvals"},
    ],
}


# --- schema --------------------------------------------------------------------------------

def test_a_well_formed_digest_passes_the_schema():
    assert schema_errors(TASKS["filing_digest"].schema, GOOD_DIGEST) == []


def test_schema_rejects_extra_fields_missing_fields_and_unknown_enums():
    assert schema_errors(TASKS["filing_digest"].schema, {**GOOD_DIGEST, "sentiment": "positive"})
    assert schema_errors(TASKS["filing_digest"].schema, {"headline": "x", "facts": []})
    bad = {"changes": [{"person": "A", "role": "B", "change": "promoted", "effective_date": None,
                        "reason": None, "quote": "x"}]}
    assert schema_errors(TASKS["people_change"].schema, bad)


# --- digest ---------------------------------------------------------------------------------

def test_a_digest_whose_quotes_are_in_the_filing_is_kept_with_page_numbers():
    out, rejected = TASKS["filing_digest"].verify(GOOD_DIGEST, ITC)
    assert rejected == []
    assert out["headline"].startswith("ITC's board approved") and out["page"] == 1
    assert [f["label"] for f in out["facts"]] == ["Effective date", "Status"]


def test_a_headline_with_a_number_its_quote_lacks_discards_the_whole_digest():
    bad = {**GOOD_DIGEST, "headline": "ITC approved a Rs 500 crore merger with Sproutlife Foods."}
    out, rejected = TASKS["filing_digest"].verify(bad, ITC)
    assert out is None and "500" in rejected[0]["reason"]


def test_an_invented_fact_is_dropped_and_the_rest_kept():
    invented = {"label": "Deal value", "value": "Rs 1,250 crore",
                "quote": "the consideration for the amalgamation is Rs 1,250 crore"}
    restated = {"label": "Parent", "value": "ITC Limited",
                "quote": "Scheme of Amalgamation of Sproutlife Foods Private Limited with the Company"}
    answer = {**GOOD_DIGEST, "facts": GOOD_DIGEST["facts"] + [invented, restated]}
    out, rejected = TASKS["filing_digest"].verify(answer, ITC)
    assert [f["label"] for f in out["facts"]] == ["Effective date", "Status"]
    assert {r["what"]: r["reason"] for r in rejected} == {
        "fact: Deal value": "quote not found in the document",
        "fact: Parent": "value is not written in its quote",
    }


def test_an_empty_headline_means_nothing_to_show():
    out, rejected = TASKS["filing_digest"].verify({"headline": "", "headline_quote": "", "facts": []}, ITC)
    assert out is None and "nothing of substance" in rejected[0]["reason"]


# --- people ---------------------------------------------------------------------------------

HDFC_CHANGE = {
    "person": "Sanjay D’Souza",
    "role": "Group Head – Business Banking, Emerging & Micro Enterprises Group",
    "change": "ceased", "effective_date": "October 31, 2026", "reason": None,
    "quote": ("Mr. Sanjay D’Souza has superannuated from the services of the Bank with effect from the close "
              "of business hours on October 31, 2026 and has accordingly ceased to be the Group Head – Business "
              "Banking, Emerging & Micro Enterprises Group"),
}


def test_a_people_change_is_kept_when_name_role_and_change_are_all_in_the_quote():
    out, rejected = TASKS["people_change"].verify({"changes": [HDFC_CHANGE]}, HDFC)
    assert rejected == []
    c = out["changes"][0]
    assert c["page"] == 1 and c["effective_date"] == "October 31, 2026" and c["top_role"] is False


def test_a_role_the_filing_does_not_state_is_discarded():
    wrong = {**HDFC_CHANGE, "role": "Chief Financial Officer"}
    out, rejected = TASKS["people_change"].verify({"changes": [wrong]}, HDFC)
    assert out is None and rejected[0]["reason"] == "the role is not written in the quote"


def test_a_change_the_quote_does_not_state_is_discarded():
    # The quote says he superannuated / ceased; it never says he was appointed.
    out, rejected = TASKS["people_change"].verify({"changes": [{**HDFC_CHANGE, "change": "appointed"}]}, HDFC)
    assert out is None and rejected[0]["reason"] == "the quote does not say the person appointed"


def test_unsupported_details_are_blanked_not_shown():
    loose = {**HDFC_CHANGE, "effective_date": "November 1, 2026", "reason": "to pursue other opportunities"}
    out, rejected = TASKS["people_change"].verify({"changes": [loose]}, HDFC)
    c = out["changes"][0]
    assert c["effective_date"] is None and c["reason"] is None
    assert {r["what"] for r in rejected} == {"effective date for Sanjay D’Souza", "reason for Sanjay D’Souza"}


def test_a_top_role_needs_the_filing_to_state_it_for_the_person():
    ceo = {"person": "Dr. Amrut Naik", "role": "Chief Executive Officer", "change": "appointed",
           "effective_date": None, "reason": None,
           "quote": next(s for s in ["Appointment of Chief Executive Officer"] if s)}
    out, _ = TASKS["people_change"].verify({"changes": [ceo]}, ALKEM)
    assert out is None   # the heading names the role but not the person
    page = " ".join(ALKEM.pages[0].split())
    start = page.index("has appointed Dr. Amrut Naik as the Chief Executive Officer")
    quote = page[start:start + 120]
    assert "Chief Executive Officer" in quote
    out, _ = TASKS["people_change"].verify({"changes": [{**ceo, "quote": quote}]}, ALKEM)
    assert out["changes"][0]["top_role"] is True


# --- selection and documents ------------------------------------------------------------------

def test_needs_digest_on_real_nse_summaries():
    assert needs_digest("Amalgamation/Merger", "Amalgamation/Merger")
    assert needs_digest("Media Statement and Presentation", "General Updates")
    assert not needs_digest("Record date for the purpose of Dividend is 06-Nov-2026", "Record Date")
    assert not needs_digest("Clarification regarding news report relating to the Company s Assam facility",
                            "Rumour Verification - Regulation 30(11)")


def test_selection_on_real_filings():
    brief_records = [json.loads(line) for line in
                     (FIXTURES / "brief" / "announcements.jsonl").read_text(encoding="utf-8").splitlines()]
    picked = {(t, r["item"]["symbol"], r["item"]["desc"]) for t, r in select(brief_records + RECORDS, headline)}
    assert ("filing_digest", "ITC", "Amalgamation/Merger") in picked
    assert ("people_change", "ALKEM", "Appointment") in picked
    assert ("people_change", "HDFCBANK", "Change in Management") in picked
    assert not any(desc == "Outcome of Board Meeting" and t == "filing_digest" and sym == "SBIN"
                   for t, sym, desc in picked)   # results: XBRL has the numbers


def test_one_pdf_attached_to_several_filings_is_one_document():
    # Trent attached the same letter to four filings with different subjects.
    a, b = doc("TRENT_29102026163044_AppointmentofDirector.pdf"), doc("TRENT_29102026163102_AppointmentofDirector.pdf")
    assert a.subject != b.subject and a.url != b.url
    task = TASKS["people_change"]
    assert engine.cache_key(task, a) == engine.cache_key(task, b)
