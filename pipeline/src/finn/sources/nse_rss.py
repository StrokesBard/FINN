"""NSE RSS feeds: no history, so they are archived continuously.

Online_announcements.xml holds only today's filings; most other feeds keep
just their latest 20 items. Anything not archived in time is gone for good.
"""
import hashlib
import re
import xml.etree.ElementTree as ET

from finn.archive import Record
from finn.http import FetchError
from finn.times import parse_exchange_time

URL = "https://nsearchives.nseindia.com/content/RSS/{}.xml"

# The feeds The Brief reads; all 23 are listed at https://www.nseindia.com/rss-feed
FEEDS = (
    "Online_announcements",          # every filing, today only
    "Financial_Results",
    "Integrated_Filing_Financials",  # results XBRL links, Mar-2025 onwards
    "Board_Meetings",
    "Corporate_action",
    "InsiderTrading",
)


def source_name(feed):
    return f"nse_rss/{feed}"


def item_key(item):
    """A content hash. RSS items carry no id, and links are not unique:
    every Financial_Results item links to the same generic page."""
    parts = (" ".join((item.get(f) or "").split()) for f in ("title", "link", "pubDate", "description"))
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def is_complete(xml_bytes):
    """False when NSE served the feed cut off mid-item (seen 2026-11-03: the
    file had 1,207 whole items, then stopped inside the 1,208th)."""
    return xml_bytes.rstrip().endswith(b"</rss>")


def _items(xml_bytes, feed):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        if b"<rss" not in xml_bytes[:500] or b"<channel>" not in xml_bytes[:2000]:
            raise FetchError(f"{feed}: not XML ({e})") from None
        # A truncated feed: keep every complete <item>. The feed is newest
        # first, so the cut loses the oldest items, which an earlier poll has.
        items = []
        for m in _ITEM.finditer(xml_bytes):
            try:
                items.append(ET.fromstring(m.group(0)))
            except ET.ParseError:
                continue
        return items
    if root.tag != "rss" or root.find("channel") is None:
        raise FetchError(f"{feed}: not an RSS document (root is <{root.tag}>)")
    return root.iterfind("./channel/item")


_ITEM = re.compile(rb"<item>.*?</item>", re.S)


def parse(xml_bytes, feed, seen_at):
    """Records for every complete <item> in a feed document."""
    records = []
    for el in _items(xml_bytes, feed):
        item = {child.tag: child.text or "" for child in el}
        raw_time = item.get("pubDate")
        records.append(Record(
            source=source_name(feed),
            key=item_key(item),
            item=item,
            first_seen=seen_at,
            published=parse_exchange_time(raw_time),
            published_raw=raw_time,
        ))
    return records


def fetch(client, feed):
    """The feed's bytes, or None if it has not changed since this client last fetched it."""
    r = client.get(URL.format(feed), conditional=True)
    return None if r is None else r.content
