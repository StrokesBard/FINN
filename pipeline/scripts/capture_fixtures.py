"""Capture real exchange responses as test fixtures.

    python scripts/capture_fixtures.py        (from pipeline/)

Writes into tests/fixtures/. Feeds are trimmed to a handful of <item> blocks,
cut out byte-for-byte; nothing inside an item is edited. Re-running replaces
the fixtures with fresh captures, so the tests must not depend on specific
companies, only on the shape and quirks of the data.
"""
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from finn.http import USER_AGENT

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*"}
RSS = "https://nsearchives.nseindia.com/content/RSS/{}.xml"
ITEM = re.compile(rb"<item>.*?</item>", re.S)


def fetch(url, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)  # no Session: no cookies kept
            break
        except requests.RequestException as e:  # nsearchives times out now and then
            print(f"  attempt {attempt}: {type(e).__name__} {url}")
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)
    print(f"  {r.status_code} {len(r.content):>8,}B {url}")
    time.sleep(1)
    return r


def trim(xml, head, tail=0):
    """Keep the first `head` and last `tail` items, byte-exact."""
    items = list(ITEM.finditer(xml))
    if not items:
        return xml
    idx = sorted(set(range(min(head, len(items)))) | set(range(max(len(items) - tail, 0), len(items))))
    start, end = items[0].start(), items[-1].end()
    return xml[:start] + b"".join(items[i].group(0) for i in idx) + xml[end:]


def save(name, content):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    print(f"    -> {path.relative_to(OUT.parent.parent)}")


def capture_robots():
    manifest = {}
    for host in ["query1.finance.yahoo.com", "finance.yahoo.com", "www.screener.in",
                 "www.nseindia.com", "nsearchives.nseindia.com", "www.bseindia.com", "api.bseindia.com"]:
        r = fetch(f"https://{host}/robots.txt")
        save(f"robots/{host}.txt", r.content)
        manifest[host] = {"status": r.status_code, "content_type": r.headers.get("Content-Type")}
    save("robots/manifest.json", json.dumps(manifest, indent=2).encode())


def capture_rss():
    # Two real polls of the main feed, a few minutes apart, to test overlap/dedup.
    first = fetch(RSS.format("Online_announcements"))
    save("rss/Online_announcements_poll1.xml", trim(first.content, 15))
    etag = first.headers.get("ETag")
    for _ in range(12):
        time.sleep(20)
        second = fetch(RSS.format("Online_announcements"))
        if second.headers.get("ETag") != etag:
            break
    save("rss/Online_announcements_poll2.xml", trim(second.content, 15))

    # Feeds chosen for their quirks: shared links, empty and odd timestamps.
    for feed, head, tail in [("Financial_Results", 4, 0), ("Integrated_Filing_Financials", 3, 0),
                             ("Annual_Reports", 3, 0), ("Offer_Documents", 2, 2),
                             ("Related_Party_Trans", 2, 2), ("Circulars", 3, 0), ("Daily_Buyback", 2, 1)]:
        r = fetch(RSS.format(feed))
        save(f"rss/{feed}.xml", trim(r.content, head, tail))


def capture_api():
    # Yesterday and today, so the fixture straddles midnight (tests day partitioning).
    today = date.today()
    r = fetch("https://www.nseindia.com/api/corporate-announcements?index=equities"
              f"&from_date={today - timedelta(days=1):%d-%m-%Y}&to_date={today:%d-%m-%Y}")
    items = r.json()  # newest first
    older = [a for a in items if not a["sort_date"].startswith(f"{today:%Y-%m-%d}")]
    pick = items[:5] + older[:3]
    pick += [a for a in items if not a["attchmntFile"].lower().endswith(".pdf") and a not in pick][:1]
    save("api/announcements.json", json.dumps(pick, indent=1, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    steps = {"robots": capture_robots, "api": capture_api, "rss": capture_rss}
    for name in sys.argv[1:] or steps:
        steps[name]()
