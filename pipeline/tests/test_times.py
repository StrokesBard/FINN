import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytest

from finn.times import IST, parse_exchange_time


# Every string is copied from a real NSE feed seen on 2026-11-03.
@pytest.mark.parametrize("raw, expected", [
    ("03-Nov-2026 16:36:31", datetime(2026, 11, 3, 16, 36, 31)),        # Online_announcements
    ("11-SEP-2026 17:49:09", datetime(2026, 9, 11, 17, 49, 9)),         # Related_Party_Trans, upper-case month
    ("21-FEB-2025 15:12.56", datetime(2025, 2, 21, 15, 12, 56)),        # Related_Party_Trans, "HH:MM.SS"
    ("03-Nov-2026 12:54", datetime(2026, 11, 3, 12, 54)),               # Sast_Regulation29, no seconds
    ("30-Sep-2026", datetime(2026, 9, 30)),                             # Offer_Documents, date only
    ("2026-11-02 18:25:25", datetime(2026, 11, 2, 18, 25, 25)),         # Daily_Buyback, ISO-ish
    ("Tue, 3 Nov 2026 00:00:00 +0530", datetime(2026, 11, 3)),          # Circulars, RFC 822
    ("03-Nov-2026 16:02:08 ", datetime(2026, 11, 3, 16, 2, 8)),         # Integrated_Filing_Financials, trailing space
])
def test_real_nse_formats_parse_to_ist(raw, expected):
    got = parse_exchange_time(raw)
    assert got == expected.replace(tzinfo=IST)
    assert got.utcoffset() == timedelta(hours=5, minutes=30)


@pytest.mark.parametrize("raw", ["", None, "   ", "Q2 FY27"])
def test_unusable_values_give_none(raw):
    assert parse_exchange_time(raw) is None


def test_every_dated_item_in_the_captured_feeds_parses(fixtures):
    seen = 0
    for path in sorted((fixtures / "rss").glob("*.xml")):
        for item in ET.parse(path).getroot().iter("item"):
            raw = item.findtext("pubDate") or ""
            if raw.strip():
                seen += 1
                assert parse_exchange_time(raw) is not None, f"{path.name}: {raw!r}"
    assert seen > 30
