"""Unusual end-of-day moves, from NSE's daily bhavcopy (UDiFF format).

A session's move is NSE's own close against NSE's own previous close, both
from that day's file. Its volume is compared with the average of the
previous N sessions' files. Every figure therefore traces to named files.
"""
import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta

URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{:%Y%m%d}_F_0000.csv.zip"
SERIES = {"EQ", "BE", "BZ"}  # stocks move between these; never filter on EQ alone
FILE_DATE = re.compile(r"_(\d{8})_F_0000\.csv\.zip$")


def url_for(day):
    return URL.format(day)


def read_bhavcopy(path, symbols):
    """{symbol: row} for the wanted symbols in one day's file."""
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            rows = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
            return {r["TckrSymb"]: r for r in rows
                    if r["TckrSymb"] in symbols and r["SctySrs"] in SERIES}


@dataclass
class Session:
    day: object          # date
    url: str
    rows: dict           # symbol -> raw bhavcopy row


def load_sessions(cache_dir, symbols):
    """Every cached session, oldest first."""
    sessions = []
    for path in sorted(cache_dir.glob("BhavCopy_NSE_CM_*.csv.zip")):
        m = FILE_DATE.search(path.name)
        if not m:
            continue
        day = datetime.strptime(m.group(1), "%Y%m%d").date()
        sessions.append(Session(day, url_for(day), read_bhavcopy(path, symbols)))
    return sessions


@dataclass
class Move:
    symbol: str
    day: object
    close: float
    prev_close: float
    change_pct: float
    volume: int
    avg_volume: float | None
    volume_multiple: float | None
    lookback: list = field(default_factory=list)   # [(date, url, volume)] used for the average
    source_url: str = ""
    price_hit: bool = False
    volume_hit: bool = False
    caveats: list = field(default_factory=list)


_ACTION = re.compile(r"bonus|split|sub-?division", re.I)


def share_count_events(corporate_actions):
    """[(ex_date, subject)] for bonuses and splits, which break volume/price comparisons."""
    out = []
    for a in corporate_actions or []:
        subject = " ".join((a.get("subject") or "").split())
        if not _ACTION.search(subject):
            continue
        try:
            ex = datetime.strptime(a.get("exDate", ""), "%d-%b-%Y").date()
        except ValueError:
            continue
        out.append((ex, subject))
    return out


def move_for(symbol, idx, sessions, thresholds, corporate_actions=None):
    """The move for `symbol` in sessions[idx], or None if it did not trade that day."""
    s = sessions[idx]
    row = s.rows.get(symbol)
    if row is None:
        return None
    close, prev = float(row["ClsPric"]), float(row["PrvsClsgPric"])
    volume = int(float(row["TtlTradgVol"]))
    n = thresholds["volume_lookback_sessions"]
    prior = [(p.day, p.url, int(float(p.rows[symbol]["TtlTradgVol"])))
             for p in sessions[:idx] if symbol in p.rows][-n:]
    m = Move(symbol, s.day, close, prev, (close / prev - 1) * 100, volume, None, None,
             lookback=prior, source_url=s.url)

    events = share_count_events(corporate_actions)
    if len(prior) < n:
        m.caveats.append(f"Only {len(prior)} earlier sessions are cached, fewer than the {n} needed "
                         "for the volume average.")
    else:
        first = prior[0][0]
        broken = [(ex, subj) for ex, subj in events if first < ex <= s.day]
        if broken:
            ex, subj = broken[-1]
            m.caveats.append(f"Volume not compared: \"{subj}\" went ex on {ex:%d %b %Y}, inside the "
                             "look-back, so earlier volumes count a different number of shares.")
        else:
            m.avg_volume = sum(v for _, _, v in prior) / len(prior)
            m.volume_multiple = volume / m.avg_volume if m.avg_volume else None
    if any(ex == s.day for ex, _ in events):
        m.caveats.append("Price move not flagged: this was the ex-date of a bonus or split.")
    else:
        m.price_hit = abs(m.change_pct) >= thresholds["price_move_pct"]
    m.volume_hit = m.volume_multiple is not None and m.volume_multiple >= thresholds["volume_multiple"]
    return m


def session_close(day, ist):
    """NSE's cash market closes at 15:30 IST; that is when a session's move happened."""
    return datetime(day.year, day.month, day.day, 15, 30, tzinfo=ist)


def previous_weekdays(day, count):
    out, d = [], day
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out
