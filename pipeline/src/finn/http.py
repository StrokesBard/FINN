"""Polite HTTP for public exchange data.

The rules from the spike, enforced in one place:
- plain requests with an honest User-Agent; no browser impersonation
- no cookies: anything a server sets is dropped, so nothing is ever sent back
- robots.txt is read (and cached for a day) before the first request to a host
- 401/403 means "not welcome": raise, never retry around it
- conditional GET: an unchanged feed costs a 304 and no body
"""
import http.cookiejar
import logging
import re
import time
from urllib.parse import urlsplit

import requests

# Kept short. On 2026-11-03 nsearchives.nseindia.com silently stalled requests
# carrying some longer UA strings; we did not probe why (that would be testing
# bot defences), we just use one honest UA and treat timeouts as transient.
USER_AGENT = "finn/0.1 (research prototype)"
PRODUCT_TOKEN = "finn"
ROBOTS_TTL = 24 * 3600

log = logging.getLogger(__name__)


class Blocked(Exception):
    """robots.txt disallows the URL, or the host answered 401/403."""


class FetchError(Exception):
    """The request failed after retries, or the response is unusable."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# --- robots.txt (RFC 9309) ---------------------------------------------------
# Before Python 3.15, urllib.robotparser ignores the `*` and `$` wildcards that
# real files use (screener.in: `Disallow: /*?q=`) and wrongly allows those URLs.

def robots_rules(status, content_type, body):
    """The rule lines to obey, given how a host answered /robots.txt.

    A 4xx means no rules; a 5xx or no answer means assume everything is
    disallowed (returns None). A host that answers with an HTML page (BSE
    serves its home page) has no robots.txt, so no rules either.
    """
    if status is None or status >= 500:
        return None
    if status >= 400:
        return []
    head = body.lstrip()[:20].lower()
    if "html" in (content_type or "").lower() or head.startswith(("<!doctype", "<html")):
        return []
    return body.splitlines()


def _groups(lines):
    """Yield (agents, [(is_allow, pattern)]) groups from robots.txt lines."""
    agents, rules, in_rules = [], [], False
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (s.strip() for s in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if in_rules:
                yield agents, rules
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
        elif field in ("allow", "disallow") and agents:
            in_rules = True
            if value:  # an empty Disallow allows everything
                rules.append((field == "allow", value))
    if agents:
        yield agents, rules


def _pattern_matches(pattern, path):
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.match(body + ("$" if anchored else ""), path) is not None


def allowed(rules, url, agent=PRODUCT_TOKEN):
    """True if `rules` (from robots_rules) let `agent` fetch `url`."""
    if rules is None:
        return False
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    agent = agent.lower()
    groups = list(_groups(rules))
    mine = [r for agents, rs in groups if agent in agents for r in rs]
    if not mine and not any(agent in agents for agents, _ in groups):
        mine = [r for agents, rs in groups if "*" in agents for r in rs]
    # Longest matching pattern wins; on a tie, allow wins.
    best = max(((len(p), is_allow) for is_allow, p in mine if _pattern_matches(p, path)), default=None)
    return best is None or best[1]


# --- client --------------------------------------------------------------------

class Client:
    def __init__(self, timeout=30, retries=2, backoff=2.0, min_interval=1.0,
                 session=None, sleep=time.sleep, clock=time.monotonic):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
        self.session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self.timeout, self.retries, self.backoff, self.min_interval = timeout, retries, backoff, min_interval
        self._sleep, self._clock = sleep, clock
        self._robots = {}      # "https://host" -> (fetched_at, rules)
        self._validators = {}  # url -> conditional-GET headers from the last 200
        self._last_hit = {}    # host -> clock() of the last request

    def get(self, url, conditional=False):
        """GET url and return the Response.

        With conditional=True, returns None if the server answers 304 Not Modified
        because nothing changed since this client last fetched the URL.
        """
        if not allowed(self._rules_for(url), url):
            raise Blocked(f"robots.txt disallows {url}")
        headers = dict(self._validators.get(url, {})) if conditional else {}
        r = self._request(url, headers)
        if r.status_code == 304:
            return None
        if conditional:
            v = {}
            if r.headers.get("ETag"):
                v["If-None-Match"] = r.headers["ETag"]
            if r.headers.get("Last-Modified"):
                v["If-Modified-Since"] = r.headers["Last-Modified"]
            self._validators[url] = v
        return r

    def _rules_for(self, url):
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(root)
        if cached and self._clock() - cached[0] < ROBOTS_TTL:
            return cached[1]
        try:
            r = self._request(root + "/robots.txt", {}, allow_status=True)
        except FetchError:
            return None  # unreachable: disallow for now, ask again next time
        rules = robots_rules(r.status_code, r.headers.get("Content-Type"), r.text)
        self._robots[root] = (self._clock(), rules)
        return rules

    def _request(self, url, headers, allow_status=False):
        host = urlsplit(url).netloc
        last_error = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (self._clock() - self._last_hit.get(host, float("-inf")))
            if wait > 0:
                self._sleep(wait)
            self._last_hit[host] = self._clock()
            try:
                r = self.session.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last_error = FetchError(f"{type(e).__name__} for {url}")
            else:
                if allow_status and r.status_code < 500:
                    return r
                if r.status_code in (401, 403):
                    raise Blocked(f"{host} answered {r.status_code} for {url}")
                if r.status_code == 304 or 200 <= r.status_code < 300:
                    return r
                last_error = FetchError(f"HTTP {r.status_code} for {url}", status=r.status_code)
                if r.status_code != 429 and r.status_code < 500:
                    break  # a 404 will not fix itself on retry
            if attempt < self.retries:
                log.info("retrying %s (%s)", url, last_error)
                self._sleep(self.backoff * 2 ** attempt)
        raise last_error
