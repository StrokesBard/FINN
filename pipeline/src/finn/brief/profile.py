"""What a management-change filing itself says about the person.

SEBI's disclosure rules make companies include a "brief profile" of anyone
they appoint, so the filing is the primary source. We quote it, trimmed to
whole sentences, and never paraphrase it.
"""
import re

from finn.brief.classify import TOP_ROLE

PROFILE = re.compile(r"brief\s+profile(\s*\(in case of appointment\))?\s*[:\-–]?\s*", re.I)
# The next numbered item or table row in the standard SEBI disclosure ends the profile.
NEXT_SECTION = re.compile(r"\s(\d{1,2}\s?[.)]\s+[A-Z]|Disclosure of relationship|Skills and capabilities|"
                          r"Relationship with|Inter-?se relationship)")
# Within a sentence: any character but a full stop, except the stop after an honorific or an
# initial ("Dr. Amrut Naik", "Mr. H. V. Goenka"), which does not end the sentence.
_IN_SENTENCE = r"(?:\b(?:Mr|Ms|Mrs|Dr|Shri|Smt|[A-Z])\.|[^.])"
# Where a filing states the role itself. Each pattern's last group is the role.
ROLE_STATEMENTS = [
    re.compile(r"\bdesignation\s*[:\-–]\s*([^.;:]{3,60})", re.I),                        # "Designation : CFO"
    re.compile(r"\b(?:appoint\w*|re-?designat\w*|elevat\w*)\b" + _IN_SENTENCE + r"{0,120}?\bas\s+(?:the\s+|an?\s+)?"
               r"([^.;]{3,60})", re.I),                                                   # "appointed Dr. X as the CEO"
    re.compile(r"\b(?:resign\w*|cessation|retire\w*)\b[^.]{0,30}?\bof\s+(?:mr|ms|mrs|dr|shri|smt)\.?\s+"
               r"[A-Z][\w.' ]{2,40}?,\s*([^,.;]{3,60})", re.I),                            # "resignation of Mr. X, CFO"
    re.compile(r"\bfrom the (?:post|position|office) of\s+([^.;]{3,60})", re.I),
]
MAX_CHARS = 700


def _clean(text):
    return " ".join((text or "").split())


PERSON = re.compile(r"\b(?:Mr|Ms|Mrs|Dr|Shri|Smt)\.?\s+((?:[A-Z][\w'\-]*\.?\s?){1,4})")


def named_person(text):
    """The surname of the first person an NSE summary names ("Appointment of Dr. Amrut Naik as CEO")."""
    m = PERSON.search(text or "")
    return m.group(1).split()[-1].strip(".") if m else None


def extract(pages, surname=None):
    """{"text", "page"} from the filing's "Brief profile" section, or None.

    A profile counts only if it is about a person (it opens with Mr/Ms/Dr/Shri/
    Smt), and, when the NSE summary names someone, only if it mentions them.
    One board-outcome PDF can carry several profiles, including an audit firm's.
    """
    for n, page in enumerate(pages, 1):
        flat = _clean(page)
        for m in PROFILE.finditer(flat):
            body = flat[m.end():]
            end = NEXT_SECTION.search(body)
            body = body[:end.start()] if end else body
            if len(body) > MAX_CHARS:
                cut = body.rfind(". ", 0, MAX_CHARS)
                body = body[:cut + 1] if cut > 0 else body[:MAX_CHARS] + "…"
            body = body.strip()
            if len(body) < 40 or not PERSON.match(body):
                continue
            if surname and surname.lower() not in body[:200].lower():
                continue
            return {"text": body, "page": n}
    return None


def top_role(pages):
    """The phrase in the filing that names a top role being filled or vacated, or None.

    Only a role the filing states for the person counts ("Designation: CFO",
    "appointed ... as the Chairman", "resignation of Mr X, CFO"). A CEO's
    signature, or a note that the appointee is the Chairman's son, does not.
    """
    for page in pages[:3]:
        flat = _clean(page)
        for pattern in ROLE_STATEMENTS:
            for m in pattern.finditer(flat):
                if TOP_ROLE.search(m.group(1)) and not re.search(r"emeritus", m.group(1), re.I):
                    # Drop the SEBI form's "appointment, re-appointment, ... death or otherwise" preamble.
                    return re.split(r"\bor otherwise\b", m.group(0))[-1].strip()
    return None
