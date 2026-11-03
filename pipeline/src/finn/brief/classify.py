"""Classify an NSE filing into a category and a tier, and say why.

Rules only, no model: every label must be explainable to the user, and the
inputs are NSE's own subject line (`desc`) and one-line summary
(`attchmntText`). Rules run in order; the first match wins. Anything no rule
matches is shown, not hidden: burying an unknown filing is the worse mistake.

Tiers: "needs_you" (material), "worth_knowing", "routine" (collapsed).
"""
import re
from dataclasses import dataclass

NEEDS_YOU, WORTH_KNOWING, ROUTINE = "needs_you", "worth_knowing", "routine"

# Category keys follow the challenge's reference list; labels are what the screen shows.
LABELS = {
    "results": "Results",
    "results_due": "Results date",
    "management_change": "Management change",
    "mna": "M&A",
    "fund_raise": "Fund raise",
    "litigation": "Litigation / regulatory",
    "material_event": "Material event",
    "credit_rating": "Credit rating",
    "pledging": "Pledging",
    "insider_trading": "Insider / promoter trade",
    "dividend": "Dividend",
    "bonus_split": "Bonus / split",
    "capex": "Capex",
    "orders_business": "Orders & business update",
    "clarification": "Exchange clarification",
    "correction": "Correction to a filing",
    "board_decision": "Board decision",
    "earnings_call": "Earnings call",
    "investor_meetings": "Investor meetings",
    "agm_egm": "Shareholder meeting",
    "routine_paperwork": "Routine paperwork",
    "unclassified": "Unclassified",
}

# Order inside a tier: lower comes first. Ties go to the newest filing.
PRIORITY = [
    "results", "management_change", "mna", "litigation", "material_event", "fund_raise",
    "pledging", "credit_rating", "correction", "insider_trading", "orders_business", "clarification",
    "board_decision", "capex", "dividend", "bonus_split", "results_due", "earnings_call", "unclassified",
    "investor_meetings", "agm_egm", "routine_paperwork",
]

TOP_ROLE = re.compile(r"\b(ceo|cfo|chief executive|chief financial|managing director|md\b|"
                      r"chairman|chairperson|whole[- ]?time director|executive director|"
                      r"joint managing|deputy managing)", re.I)


@dataclass(frozen=True)
class Classification:
    category: str
    tier: str
    reason: str          # why this category and tier, in plain words
    evidence: str        # the NSE text the rule matched on

    @property
    def label(self):
        return LABELS[self.category]


def _text(item):
    return (item.get("attchmntText") or "").strip()


def _has(pattern, text):
    return re.search(pattern, text, re.I) is not None


RESULTS_TEXT = (r"financial results?|results? for the (quarter|period|half|year)"
                r"|financials? (of the company )?for the (quarter|half|year)")
FUND_TEXT = r"raising of funds?|fund ?rais|issue of equity|\bqip\b|preferential|rights issue|debentures|\bncds?\b"
ROUTINE_TEXT = (r"\brta\b|registrar|share transfer agent|\bcin\b|demat report|loss of share certificate|"
                r"duplicate share|regulation 74\s*\(5\)|newspaper|trading window|e-?voting|book closure")


def classify(item):
    desc = " ".join((item.get("desc") or "").split())   # NSE sometimes double-spaces subjects
    text = _text(item)
    both = f"{desc} {text}"
    subj = f'NSE subject "{desc}"'

    def c(category, tier, reason, evidence=subj):
        return Classification(category, tier, reason, evidence)

    # --- results ---------------------------------------------------------------
    if desc in ("Outcome of Board Meeting", "Financial Result Updates") and _has(RESULTS_TEXT, text):
        return c("results", NEEDS_YOU, "Quarterly or annual results are material by default.",
                 f'{subj}; summary mentions financial results')
    if desc == "Integrated Filing- Financial":
        return c("results", WORTH_KNOWING, "The structured (XBRL) copy of the results.")
    if desc == "Press Release" and _has(r"\bresults?\b|\bQ[1-4](?:\b|\s*FY)|quarter", text):
        return c("results", NEEDS_YOU, "A press release about results belongs with the results.",
                 f'{subj}; summary mentions results')
    if desc == "Investor Presentation":
        return c("results", WORTH_KNOWING, "Investor presentations usually accompany results.")
    if desc == "Clarification - Financial Results":
        return c("results", NEEDS_YOU, "The company corrected or clarified its results.")
    if _has(r"board meeting", desc) and _has(r"intimation|to consider", both) and _has(r"result", text):
        return c("results_due", WORTH_KNOWING, "Announces when the board will approve results.")

    # --- people ------------------------------------------------------------------
    if desc in ("Resignation of Statutory Auditor",):
        return c("management_change", NEEDS_YOU, "A statutory auditor resigning is a classic red flag.")
    if desc in ("Change in Management", "Appointment", "Resignation of Director/KMP/SMP", "Change in Director(s)",
                "Cessation", "Resignation", "Retirement", "Demise", "Change in Directors/KMP/SMP/Auditor/RTA"):
        m = TOP_ROLE.search(text)
        if m:
            return c("management_change", NEEDS_YOU, "A change at the top (CEO, CFO, MD or similar).",
                     f'{subj}; summary names the role "{m.group(0)}"')
        return c("management_change", WORTH_KNOWING,
                 "A change below the top roles (director, KMP or senior management).")
    if desc == "Change in Company Secretary/Compliance Officer":
        return c("management_change", ROUTINE, "Company secretary changes rarely move the stock.")

    # --- corporate events -------------------------------------------------------
    if desc in ("Acquisition", "Amalgamation/Merger", "Scheme of Arrangement", "Sale or disposal",
                "Other Restructuring", "Acquisition (including agreement to acquire)-XBRL"):
        return c("mna", NEEDS_YOU, "Acquisitions, mergers, demergers and disposals are material.")
    if desc in ("Action(s) taken or orders passed", "Action(s) initiated or orders passed",
                "Corporate Insolvency Resolution Process", "Actions initiated/taken or orders passed-XBRL") \
            or desc.startswith("Pendency of Litigation"):
        return c("litigation", NEEDS_YOU, "Regulatory orders, penalties and disputes are material.")
    if desc in ("Disclosure of material issue", "Strikes/Lockouts/Disturbances", "Disruption of Operations",
                "Closure of operations", "Giving guarantees/indemnity/ becoming a surety for third party",
                "Fraud/Default/Arrest", "Defaults on Payment of Interest/Principal", "Final forensic audit report",
                "Reasons for Delayed/Non-submission of Financial Results", "Diversification/Disinvestment",
                "Postponement of commercial production/operations") or desc.startswith("Delay/default"):
        return c("material_event", NEEDS_YOU, "The company itself flagged this as a material event.")
    if desc in ("Issue of Securities", "Public Announcement - Buyback of Shares", "Post Buyback Public Announcement",
                "Offer for sale", "Buyback", "Closure of Buy Back") or (desc == "Allotment of Securities"
                                      and _has(r"preferential|qip|rights|warrant|non-convertible|ncd|"
                                               r"commercial paper", text)):
        return c("fund_raise", NEEDS_YOU, "Raising or returning capital changes the share count or debt.")
    if desc in ("Corrigendum", "Addendum") or desc.startswith("Reply to Clarification"):
        return c("correction", WORTH_KNOWING, "Corrects or adds to an earlier filing.")
    if desc.startswith("Credit Rating"):
        if _has(r"downgrad|negative|watch", text):
            return c("credit_rating", NEEDS_YOU, "A rating downgrade or negative outlook.",
                     f'{subj}; summary mentions a downgrade or negative outlook')
        return c("credit_rating", WORTH_KNOWING, "A rating action without a downgrade.")
    if _has(r"pledg|encumbrance", both):
        return c("pledging", NEEDS_YOU, "Promoter pledging is a risk signal.", f"{subj}; mentions pledge/encumbrance")
    if desc.startswith(("Disclosure under SEBI Takeover", "Disclosure under SEBI (Prohibition of Insider")):
        return c("insider_trading", WORTH_KNOWING, "A promoter or large holder changed their stake.")

    # --- business ------------------------------------------------------------------
    if desc in ("Bagging/Receiving of orders/contracts", "Awarding of order(s)/contract(s)", "Agreements",
                "Arrangements for strategic, technical, manufacturing, or marketing tie up", "Product launch",
                "Monthly Business Updates", "Press Release", "Press Release (Revised)") \
            or desc.startswith("Granting/withdrawal"):
        return c("orders_business", WORTH_KNOWING, "Business news from the company: orders, launches, tie-ups.")
    if desc in ("Capacity addition", "Commencement of commercial production/operations"):
        return c("capex", WORTH_KNOWING, "New capacity or a plant starting production.")
    if desc in ("News Verification", "Rumour Verification - Regulation 30(11)", "Price movement", "Spurt in Volume") \
            or desc.startswith("Clarification"):
        return c("clarification", WORTH_KNOWING, "The exchange asked the company to explain news or a price move.")
    if desc == "Dividend" or (desc in ("Record Date", "Record Date Updates") and _has(r"dividend", text)):
        return c("dividend", WORTH_KNOWING, "A dividend or its record date.")
    if _has(r"\bbonus\b|sub-?division|stock split|split of", both):
        return c("bonus_split", WORTH_KNOWING, "A bonus or split changes the share count.",
                 f"{subj}; mentions bonus/split")

    # --- calls, meetings, paperwork ------------------------------------------------
    if desc == "Analysts/Institutional Investor Meet/Con. Call Updates" or desc.startswith("Analyst/Investor Meet"):
        if _has(r"transcript|recording|audio", text):
            return c("earnings_call", WORTH_KNOWING, "The call transcript or recording is out.",
                     f"{subj}; summary mentions a transcript/recording")
        return c("investor_meetings", ROUTINE, "Schedules of analyst and investor meetings.")
    if desc in ("Shareholders meeting", "Notice Of Shareholders Meetings-XBRL", "Voting Results") \
            or _has(r"postal ballot", both):
        return c("agm_egm", ROUTINE, "AGM/EGM and postal-ballot notices and results.")
    if desc in ("Copy of Newspaper Publication", "Trading Window", "ESOP/ESOS/ESPS", "Monitoring Agency Report",
                "Structural Digital Database", "Address Change", "Amendment to AOA/MOA", "Committee Meeting Updates",
                "Change in Auditors", "Options to purchase securities", "Allotment of Securities",
                "Related Party Transactions", "Record Date", "Record Date Updates") \
            or desc.startswith("Certificate under SEBI") or desc.startswith("Statement of deviation") \
            or desc.startswith("Compliance"):
        return c("routine_paperwork", ROUTINE, "Routine compliance paperwork.")

    # --- catch-alls ("Updates", "General Updates", "Outcome of Board Meeting" without results) ---
    if desc == "Outcome of Board Meeting":
        if _has(FUND_TEXT, text):
            return c("fund_raise", NEEDS_YOU, "The board approved raising money.",
                     f"{subj}; summary mentions a fund raise")
        if _has(r"dividend", text):
            return c("dividend", WORTH_KNOWING, "The board declared a dividend.",
                     f"{subj}; summary mentions a dividend")
        return c("board_decision", WORTH_KNOWING, "A board meeting outcome that is not results.")
    if _has(ROUTINE_TEXT, text):
        return c("routine_paperwork", ROUTINE, "Routine administration (registrar, CIN, demat, notices).",
                 f"{subj}; summary is about routine administration")
    if desc == "Name Change":
        return c("board_decision", WORTH_KNOWING, "The company is changing its name.")
    if _has(r"transcript", text):
        return c("earnings_call", WORTH_KNOWING, "The call transcript is out.",
                 f"{subj}; summary mentions a transcript")
    if _has(r"acqui|merger|amalgamat|demerg", text):
        return c("mna", NEEDS_YOU, "Mentions an acquisition, merger or demerger.",
                 f"{subj}; summary mentions acquisition/merger")
    if _has(r"\border", text):
        return c("orders_business", WORTH_KNOWING, "Mentions an order.", f"{subj}; summary mentions an order")
    return c("unclassified", WORTH_KNOWING,
             "No rule matched, so it is shown rather than hidden.")
