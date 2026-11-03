"""Is a model's quote really in the document?

Comparison is on normalised text: case, curly quotes, dash variants, ligatures and
whitespace (including the stray spaces PDF extraction inserts around hyphens) are
evened out. Nothing else is forgiven: a quote with words added, dropped,
reordered or elided ("...") is not found and its claim is discarded.
"""
import re
import unicodedata

MIN_QUOTE, MAX_QUOTE = 15, 600
_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                            "—": "-", "−": "-", " ": " ", "­": ""})
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").translate(_TRANSLATE).lower()
    text = re.sub(r"\s*-\s*", "-", text)          # "hands -on" and "hands- on" read as "hands-on"
    return re.sub(r"\s+", " ", text).strip()


def quote_problem(quote, document):
    """None if the quote is usable, else the reason it is not."""
    if not isinstance(quote, str):
        return "quote missing"
    q = normalize(quote)
    if len(q) < MIN_QUOTE:
        return f"quote shorter than {MIN_QUOTE} characters"
    if len(q) > MAX_QUOTE:
        return f"quote longer than {MAX_QUOTE} characters"
    if "..." in q or "…" in quote:
        return "quote is elided"
    if q not in normalize(document):
        return "quote not found in the document"
    return None


def page_of(quote, pages):
    """1-based page that contains the quote, or None."""
    q = normalize(quote)
    for n, page in enumerate(pages, 1):
        if q in normalize(page):
            return n
    return None


def numbers(text):
    """Numeric tokens with grouping commas removed: "1,469.0 crore" -> {"1469.0"}."""
    return {n.replace(",", "") for n in _NUMBER.findall(text or "")}


def unquoted_numbers(claim, quote):
    """Numbers stated in a claim that its quote does not contain."""
    return sorted(numbers(claim) - numbers(quote))
