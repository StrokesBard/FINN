import json

from conftest import FIXTURES

from finn.brief import profile

PDF = FIXTURES / "brief" / "pdf_text"


def pages(prefix):
    path = next(PDF.glob(f"{prefix}*.json"))
    return json.loads(path.read_text(encoding="utf-8"))["pages"]


def test_the_appointee_profile_is_quoted_from_the_filing():
    got = profile.extract(pages("ALKEM_"), surname="Naik")
    assert got["text"].startswith("Dr. Amrut Naik is")
    assert got["page"] >= 1 and len(got["text"]) <= 701


def test_a_board_outcome_with_an_audit_firm_profile_gives_the_persons_not_the_firms():
    # UPL's PDF profiles its new auditor (S R B C & CO LLP) before the new directors.
    got = profile.extract(pages("UPL_02112026153430"), surname="Shrivastava")
    assert got["text"].startswith("Shri Shatmanyu Shrivastava")
    unnamed = profile.extract(pages("UPL_02112026153430"))
    assert unnamed is None or not unnamed["text"].startswith("S R B C")


def test_a_named_person_without_a_profile_gets_none_rather_than_someone_elses():
    assert profile.extract(pages("UPL_02112026153604"), surname="Tandon") is None


def test_a_pointer_to_an_annexure_is_not_a_profile():
    # HAL: "Brief profile of Shri P B Rangarao is enclosed herewith as Annexure."
    assert profile.extract(pages("HAL_")) is None


def test_names_in_nse_summaries():
    assert profile.named_person("Appointment of Dr. Amrut Naik as Chief Executive Officer (CEO)") == "Naik"
    assert profile.named_person("Retirement of Shri Ashish Bhatt, Senior Vice President") == "Bhatt"
    assert profile.named_person("change in Management") is None


def test_top_role_needs_the_role_stated_for_the_person():
    # KEC: the appointee "is the son of Mr. H. V. Goenka (Chairman of the Board)" - not a Chairman change.
    assert profile.top_role(pages("KEC_")) is None
    # Trent: Noel Tata retires "from the office of Chairman and Director".
    assert "Chairman" in profile.top_role(pages("TRENT_"))


def test_top_role_evidence_skips_the_sebi_form_preamble():
    phrase = profile.top_role(pages("DIXON_"))
    assert "Executive Director" in phrase
    assert not phrase.lower().startswith("appointment, reappointment")
