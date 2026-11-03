"""NSE corporate-announcements API: the main filings feed, with symbol and ISIN.

It reaches back to 2004, so strictly it needs no archiving. But it is
undocumented and could vanish or change, so we keep what we poll; that also
records when FINN first saw each filing.
"""
import hashlib
import json

from finn.archive import Record
from finn.http import FetchError
from finn.times import parse_exchange_time

URL = ("https://www.nseindia.com/api/corporate-announcements"
       "?index=equities&from_date={:%d-%m-%Y}&to_date={:%d-%m-%Y}")
SOURCE = "nse_api/announcements"


def item_key(item):
    """NSE's seq_id, which is unique per filing; a content hash if it is ever missing."""
    seq = str(item.get("seq_id") or "").strip()
    if seq:
        return seq
    return "sha1:" + hashlib.sha1(json.dumps(item, sort_keys=True).encode("utf-8")).hexdigest()


def parse(payload, seen_at):
    if not isinstance(payload, list):
        raise FetchError(f"announcements API returned {type(payload).__name__}, expected a list")
    records = []
    for item in payload:
        if not isinstance(item, dict):
            raise FetchError("announcements API returned a non-object item")
        raw_time = item.get("sort_date") or item.get("an_dt")
        records.append(Record(
            source=SOURCE,
            key=item_key(item),
            item=item,
            first_seen=seen_at,
            published=parse_exchange_time(raw_time),
            published_raw=raw_time,
        ))
    return records


def fetch(client, start, end):
    """Every equity announcement disseminated between two dates (inclusive)."""
    r = client.get(URL.format(start, end))
    try:
        return r.json()
    except ValueError:
        raise FetchError("announcements API did not return JSON") from None
