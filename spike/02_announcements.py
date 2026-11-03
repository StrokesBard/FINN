"""Spike 2: corporate announcements / filings.

Candidates:
  a) NSE JSON API (what nseindia.com's own pages call)   -> plain request only
  b) NSE RSS feeds on nsearchives.nseindia.com/content/RSS/
  c) BSE JSON API (api.bseindia.com)                     -> plain request only
  d) BSE RSS / XML candidates
"""
import collections
import re

import feedparser

from _common import get

print("a) NSE JSON API, plain request, no cookies")
for u in ["https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=INFY",
          "https://www.nseindia.com/api/corporate-announcements?index=equities"]:
    r = get(u, timeout=15)
    if r is not None:
        print(f"    body head: {r.content[:160]!r}")

print("\n   NSE RSS index page")
r = get("https://www.nseindia.com/rss-feed", timeout=15)
feeds_from_page = []
if r is not None and r.status_code == 200:
    feeds_from_page = sorted(set(re.findall(r"https://nsearchives\.nseindia\.com/content/RSS/[\w\-]+\.xml", r.text)))
    print(f"    feed URLs found on page: {len(feeds_from_page)}")
    for f in feeds_from_page:
        print("     ", f)

print("\nb) NSE RSS feeds")
guesses = ["Online_announcements", "Financial_Results", "Board_Meetings", "Corporate_action",
           "Insider_Trading", "Annual_Reports", "Shareholding_Pattern", "Corporate_Governance",
           "Credit_Rating", "Investor_Complaints", "Circulars", "Press_Release", "Offer_Documents"]
urls = feeds_from_page or [f"https://nsearchives.nseindia.com/content/RSS/{g}.xml" for g in guesses]
ok_feeds = {}
for u in urls:
    r = get(u, timeout=20)
    if r is None or r.status_code != 200 or b"<rss" not in r.content[:500]:
        continue
    f = feedparser.parse(r.content)
    dates = [e.get("published", "") for e in f.entries]
    print(f"    {len(f.entries):>4} items | first: {dates[0] if dates else '-'} | last: {dates[-1] if dates else '-'}")
    ok_feeds[u] = f

if ok_feeds:
    ann = next((f for u, f in ok_feeds.items() if "announcement" in u.lower()), None)
    sample = ann or next(iter(ok_feeds.values()))
    print("\n   sample entries (fields + 3 items):")
    print("    keys:", sorted(sample.entries[0].keys()))
    for e in sample.entries[:3]:
        print("    -", e.get("title"), "|", e.get("published"))
        print("      link:", e.get("link"))
        print("      desc:", (e.get("summary") or "")[:220].replace("\n", " "))
    if ann:
        # what does the subject vocabulary look like? (drives the classifier)
        subj = collections.Counter()
        for e in ann.entries:
            s = (e.get("summary") or "")
            m = re.search(r"\|SUBJECT:\s*([^|]+)", s, re.I)
            subj[(m.group(1) if m else s[:60]).strip()] += 1
        print("\n   most common subjects in announcements feed:")
        for k, v in subj.most_common(25):
            print(f"    {v:>3}  {k}")
        exts = collections.Counter(re.sub(r".*\.", "", e.get("link", "")).lower() for e in ann.entries)
        print("   attachment types:", dict(exts))

print("\nc) BSE JSON API, plain request")
for u in ["https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1"
          "&strPrevDate=20261102&strScrip=&strSearch=P&strToDate=20261103&strType=C&subcategory=-1"]:
    r = get(u, timeout=15)
    if r is not None:
        print(f"    body head: {r.content[:160]!r}")

print("\nd) BSE RSS / XML candidates")
for u in ["https://www.bseindia.com/data/xml/notices.xml",
          "https://www.bseindia.com/data/xml/sensexrss.xml",
          "https://www.bseindia.com/rss-feed.html",
          "https://www.bseindia.com/Rss.aspx"]:
    r = get(u, timeout=15)
    if r is not None and r.status_code == 200:
        print(f"    body head: {r.content[:160]!r}")
