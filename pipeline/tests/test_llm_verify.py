"""Quote checking against the real text the pipeline extracted from filing PDFs."""
import json

import pytest
from conftest import FIXTURES

from finn.llm.verify import normalize, page_of, quote_problem, unquoted_numbers


def pages(name):
    return json.loads((FIXTURES / "llm" / "pdf_text" / f"{name}.json").read_text(encoding="utf-8"))["pages"]


HDFC = pages("HDFCBANK3_31102026221631_SE_INTIMATION-_Sanjay_Dsouza.pdf")
ITC = pages("ITC_02112026184512_SE_Sproutlife_.pdf")


def text(p):
    return "\n\n".join(p)


def test_normalisation_evens_out_pdf_and_typography_noise():
    assert normalize("Sanjay D’Souza") == normalize("Sanjay D'Souza")
    assert normalize("Group Head – Business") == normalize("Group Head - Business")
    assert normalize("hands -on") == normalize("hands-on") == normalize("hands - on")
    assert normalize("a  b\n c") == "a b c"


def test_an_exact_passage_is_found_even_across_line_breaks_and_curly_quotes():
    # Real HDFC Bank letter; the PDF uses a curly apostrophe in D’Souza.
    q = "Mr. Sanjay D'Souza has superannuated from the services of the Bank"
    assert quote_problem(q, text(HDFC)) is None
    assert page_of(q, HDFC) == 1


def test_a_tidied_quote_is_not_the_document():
    # pypdf read ITC's date as "202 6"; a model that "fixes" it to 2026 is not quoting.
    assert "202 6" in text(ITC)
    exact = "at the meeting held today i.e., 2nd November, 202 6 has approved the Scheme of Amalgamation"
    tidied = "at the meeting held today i.e., 2nd November, 2026 has approved the Scheme of Amalgamation"
    assert quote_problem(exact, text(ITC)) is None
    assert quote_problem(tidied, text(ITC)) == "quote not found in the document"


@pytest.mark.parametrize("quote, problem", [
    ("Scheme of Amalgamation of Sproutlife ... with the Company", "quote is elided"),
    ("Sproutlife", "quote shorter than 15 characters"),
    ("approved the Scheme of Amalgamation of Sproutlife Foods Public Limited", "quote not found in the document"),
    (None, "quote missing"),
])
def test_unusable_quotes_say_why(quote, problem):
    assert quote_problem(quote, text(ITC)) == problem


def test_numbers_in_a_claim_must_be_in_its_quote():
    assert unquoted_numbers("effective 1st April, 2026", "will take effect from 1st April, 2026") == []
    assert unquoted_numbers("deal worth Rs 1,250 crore", "the Board approved the scheme") == ["1250"]
    assert unquoted_numbers("Rs 1,250 crore", "Rs. 1250 crore") == []
