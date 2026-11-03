import email.message
import urllib.request
import urllib.robotparser

import pytest
import requests

from conftest import FakeResponse, FakeSession, robots_response
from finn.http import Blocked, Client, FetchError, allowed, robots_rules


def rules(host):
    r = robots_response(host)
    return robots_rules(r.status_code, r.headers["Content-Type"], r.text)


# --- robots.txt, against the real files ------------------------------------------

def test_yahoo_api_hosts_disallow_everything():
    # This is why yfinance is not used.
    assert not allowed(rules("query1.finance.yahoo.com"),
                       "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS")


def test_named_ai_crawler_groups_apply_to_them_not_to_us():
    r = rules("finance.yahoo.com")
    assert not allowed(r, "https://finance.yahoo.com/quote/INFY.NS/", agent="ClaudeBot")
    assert allowed(r, "https://finance.yahoo.com/quote/INFY.NS/")


def test_longest_match_wins_and_allow_breaks_ties():
    r = rules("finance.yahoo.com")
    # Disallow: /quote/*/earnings/*.html  vs  Allow: /quote/*/earnings/*-*-2026-*-*.html
    assert not allowed(r, "https://finance.yahoo.com/quote/AAPL/earnings/summary.html")
    assert allowed(r, "https://finance.yahoo.com/quote/AAPL/earnings/aapl-q1-2026-earnings-call.html")


def test_screener_query_wildcards_are_honoured():
    r = rules("www.screener.in")
    assert allowed(r, "https://www.screener.in/company/INFY/consolidated/")
    assert not allowed(r, "https://www.screener.in/api/company/search/?q=infy")
    assert not allowed(r, "https://www.screener.in/screens/123/value/?page=2")
    assert not allowed(r, "https://www.screener.in/company/source/quarter/6596/")


def test_stdlib_robotparser_misses_those_wildcards():
    # The reason finn.http has its own matcher.
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(robots_response("www.screener.in").text.splitlines())
    assert rp.can_fetch("finn", "https://www.screener.in/api/company/search/?q=infy")


def test_nse_allows_its_api_but_not_test_paths():
    r = rules("www.nseindia.com")
    assert allowed(r, "https://www.nseindia.com/api/corporate-announcements?index=equities")
    assert not allowed(r, "https://www.nseindia.com/market-data-test")


@pytest.mark.parametrize("host", ["nsearchives.nseindia.com", "www.bseindia.com"])
def test_missing_or_html_robots_means_no_rules(host):
    # nsearchives answers 404; BSE answers /robots.txt with its HTML home page.
    assert rules(host) == []
    assert allowed(rules(host), f"https://{host}/anything")


@pytest.mark.parametrize("status", [None, 500, 503])
def test_unreachable_robots_means_disallow_everything(status):
    assert robots_rules(status, "text/html", "") is None
    assert not allowed(None, "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml")


# --- client behaviour ----------------------------------------------------------------

FEED = "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml"
ARCHIVE_ROBOTS = "https://nsearchives.nseindia.com/robots.txt"


def client_for(routes):
    session = FakeSession(routes)
    sleeps = []
    return Client(session=session, sleep=sleeps.append), session, sleeps


def test_disallowed_url_is_never_requested():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS"
    client, session, _ = client_for({"https://query1.finance.yahoo.com/robots.txt":
                                     [robots_response("query1.finance.yahoo.com")]})
    with pytest.raises(Blocked):
        client.get(url)
    assert [u for u, _ in session.calls] == ["https://query1.finance.yahoo.com/robots.txt"]


def test_403_is_blocked_not_retried():
    client, session, _ = client_for({ARCHIVE_ROBOTS: [robots_response("nsearchives.nseindia.com")],
                                     FEED: [FakeResponse(403)]})
    with pytest.raises(Blocked):
        client.get(FEED)
    assert [u for u, _ in session.calls].count(FEED) == 1


def test_conditional_get_sends_validators_and_returns_none_on_304():
    # Validators exactly as NSE sent them for this feed.
    first = FakeResponse(200, b"<rss/>", {"ETag": 'W/"2084-1793682028838"',
                                          "Last-Modified": "Tue, 03 Nov 2026 05:00:28 GMT"})
    client, session, _ = client_for({ARCHIVE_ROBOTS: [robots_response("nsearchives.nseindia.com")],
                                     FEED: [first, FakeResponse(304)]})
    assert client.get(FEED, conditional=True) is first
    assert client.get(FEED, conditional=True) is None
    sent = [h for u, h in session.calls if u == FEED][1]
    assert sent == {"If-None-Match": 'W/"2084-1793682028838"',
                    "If-Modified-Since": "Tue, 03 Nov 2026 05:00:28 GMT"}


def test_robots_is_fetched_once_per_host():
    client, session, _ = client_for({ARCHIVE_ROBOTS: [robots_response("nsearchives.nseindia.com")],
                                     FEED: [FakeResponse(200, b"<rss/>")]})
    client.get(FEED)
    client.get(FEED)
    assert [u for u, _ in session.calls].count(ARCHIVE_ROBOTS) == 1


def test_timeouts_are_retried_with_backoff():
    # nsearchives really did time out repeatedly while these fixtures were captured.
    client, session, sleeps = client_for({ARCHIVE_ROBOTS: [robots_response("nsearchives.nseindia.com")],
                                          FEED: [requests.ReadTimeout(), FakeResponse(200, b"<rss/>")]})
    assert client.get(FEED).status_code == 200
    assert 2.0 in sleeps  # backoff before the retry


def test_404_fails_fast_with_status():
    client, session, _ = client_for({ARCHIVE_ROBOTS: [robots_response("nsearchives.nseindia.com")],
                                     FEED: [FakeResponse(404)]})
    with pytest.raises(FetchError) as e:
        client.get(FEED)
    assert e.value.status == 404
    assert [u for u, _ in session.calls].count(FEED) == 1


def test_unreachable_robots_blocks_now_and_is_asked_again_later():
    client, session, _ = client_for({ARCHIVE_ROBOTS: [requests.ReadTimeout()] * 3
                                     + [robots_response("nsearchives.nseindia.com")],
                                     FEED: [FakeResponse(200, b"<rss/>")]})
    with pytest.raises(Blocked):
        client.get(FEED)
    assert client.get(FEED).status_code == 200


def test_session_refuses_cookies():
    class SetsCookie:
        def info(self):
            msg = email.message.Message()
            msg["Set-Cookie"] = "bm_sz=abc123; Domain=.nseindia.com; Path=/; Secure"
            return msg

    request = urllib.request.Request("https://www.nseindia.com/api/corporate-announcements")
    plain = requests.cookies.RequestsCookieJar()
    plain.extract_cookies(SetsCookie(), request)
    assert len(plain) == 1  # a default jar would keep it...

    client, _, _ = client_for({})
    client.session.cookies.extract_cookies(SetsCookie(), request)
    assert len(client.session.cookies) == 0  # ...ours never does
