"""Exchange timestamps.

NSE stamps everything in IST but writes it a dozen ways, sometimes inside one
feed. Every format below was seen in a real feed on 2026-11-03.
"""
from datetime import datetime, timedelta, timezone

# A fixed offset, not zoneinfo: IST has no DST, and Windows has no tz database
# unless the tzdata package is installed.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

_FORMATS = (
    "%d-%b-%Y %H:%M:%S",          # 03-Nov-2026 16:02:29 / 11-SEP-2026 17:49:09
    "%d-%b-%Y %H:%M",             # 03-Nov-2026 12:54
    "%d-%b-%Y %H:%M.%S",          # 21-FEB-2025 15:12.56 (sic)
    "%d-%b-%Y",                   # 30-Sep-2026
    "%Y-%m-%d %H:%M:%S",          # 2026-11-02 18:25:25
    "%a, %d %b %Y %H:%M:%S %z",   # Tue, 3 Nov 2026 00:00:00 +0530
)


def parse_exchange_time(raw):
    """Parse an NSE timestamp into an aware IST datetime, or None if unusable."""
    text = " ".join((raw or "").split())
    if not text:
        return None
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)
    return None


def now_ist():
    return datetime.now(IST)
