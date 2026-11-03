"""Shared helpers for the data-source spikes.

Rules enforced here (from the spike brief):
- plain HTTP client (requests), honest User-Agent, no cookies carried between calls
- robots.txt checked before every fetch; a disallowed URL is never requested
"""
import time
import urllib.robotparser
from urllib.parse import urlsplit

import requests

UA = "finn-spike/0.1 (+research prototype; contact via repo)"
HEADERS = {"User-Agent": UA, "Accept": "*/*"}

_robots = {}


def robots_verdict(url):
    """Return (allowed, note) for url, per that host's robots.txt.

    Missing robots.txt (404) means no rules. A 401/403 on robots.txt is
    recorded separately: RFC 9309 says a 4xx means "unavailable, may crawl",
    but Python's robotparser treats 401/403 as disallow-all, so we surface it.
    """
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots:
        try:
            r = requests.get(root + "/robots.txt", headers=HEADERS, timeout=20)
            status, body = r.status_code, r.text
        except requests.RequestException as e:
            status, body = None, str(e)
        rp = urllib.robotparser.RobotFileParser()
        if status == 200 and "<html" not in body[:500].lower():
            rp.parse(body.splitlines())
            note = "robots.txt present"
        elif status == 200:
            rp.parse([])
            note = "robots.txt path serves HTML (no rules)"
        elif status in (401, 403):
            rp.parse([])
            note = f"robots.txt returned {status} (host blocks this client)"
        else:
            rp.parse([])
            note = f"robots.txt returned {status} (no rules)"
        _robots[root] = (rp, note)
    rp, note = _robots[root]
    return rp.can_fetch(UA, url), note


def get(url, **kw):
    """robots-checked GET. Returns the Response, or None if robots disallows."""
    allowed, note = robots_verdict(url)
    if not allowed:
        print(f"  SKIP (robots disallows) {url}")
        return None
    t = time.time()
    try:
        r = requests.get(url, headers={**HEADERS, **kw.pop("headers", {})},
                         timeout=kw.pop("timeout", 30), **kw)
    except requests.RequestException as e:
        print(f"  ERR  {type(e).__name__}: {e}  {url}")
        return None
    ms = int((time.time() - t) * 1000)
    ctype = r.headers.get("Content-Type", "")
    print(f"  {r.status_code} {len(r.content):>9,}B {ms:>5}ms {ctype[:40]:<40} {url}")
    time.sleep(0.5)  # be polite
    return r
