import json
import types
from datetime import date, datetime

import pytest

from conftest import SEEN, FakeResponse
from finn import cli, ingest
from finn.http import Blocked
from finn.sources import nse_announcements, nse_rss
from finn.times import IST

RSS_MAIN = nse_rss.URL.format("Online_announcements")
RSS_RESULTS = nse_rss.URL.format("Financial_Results")
TODAY = nse_announcements.URL.format(date(2026, 11, 3), date(2026, 11, 3))
FEEDS = ["Online_announcements", "Financial_Results"]


class FakeClient:
    """Answers like finn.http.Client: bytes -> 200, None -> 304 (unchanged), exception -> raised."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.session = types.SimpleNamespace(cookies=[])

    def get(self, url, conditional=False):
        self.calls.append(url)
        r = self.responses[url]
        if isinstance(r, Exception):
            raise r
        return None if r is None else FakeResponse(200, r)


@pytest.fixture(autouse=True)
def fresh_archive_cache():
    ingest._archives.clear()


@pytest.fixture
def responses(fixtures, api_items):
    return {
        RSS_MAIN: (fixtures / "rss" / "Online_announcements_poll1.xml").read_bytes(),
        RSS_RESULTS: (fixtures / "rss" / "Financial_Results.xml").read_bytes(),
        TODAY: json.dumps(api_items).encode(),
    }


def test_a_pass_archives_every_source_and_a_second_pass_adds_nothing(tmp_path, responses, api_items):
    first = ingest.poll_once(FakeClient(responses), tmp_path, feeds=FEEDS, now=SEEN)
    assert [(r.source, r.new, r.error) for r in first] == [
        ("nse_rss/Online_announcements", responses[RSS_MAIN].count(b"<item>"), None),
        ("nse_rss/Financial_Results", responses[RSS_RESULTS].count(b"<item>"), None),
        ("nse_api/announcements", len(api_items), None),
    ]
    assert all(f.exists() for r in first for f in r.files)

    ingest._archives.clear()  # as if the process restarted
    second = ingest.poll_once(FakeClient(responses), tmp_path, feeds=FEEDS, now=SEEN)
    assert [r.new for r in second] == [0, 0, 0]
    assert [r.fetched for r in second] == [r.fetched for r in first]


def test_a_cut_off_feed_is_archived_with_a_note(tmp_path, responses, fixtures):
    responses[RSS_MAIN] = (fixtures / "rss" / "Online_announcements_truncated.xml").read_bytes()
    main = ingest.poll_once(FakeClient(responses), tmp_path, feeds=FEEDS[:1], api=False, now=SEEN)[0]
    assert main.error is None and main.new == responses[RSS_MAIN].count(b"</item>")
    assert "cut off" in main.note


def test_an_unchanged_feed_is_reported_as_such(tmp_path, responses):
    responses[RSS_MAIN] = None
    main = ingest.poll_once(FakeClient(responses), tmp_path, feeds=FEEDS[:1], api=False, now=SEEN)[0]
    assert main.unchanged and main.new == 0 and main.error is None


def test_one_blocked_source_does_not_stop_the_others(tmp_path, responses, api_items):
    responses[RSS_MAIN] = Blocked("nsearchives.nseindia.com answered 403")
    results = ingest.poll_once(FakeClient(responses), tmp_path, feeds=FEEDS, now=SEEN)
    assert "403" in results[0].error
    assert results[1].error is None and results[2].new == len(api_items)


@pytest.mark.parametrize("now, start", [
    (datetime(2026, 11, 4, 0, 30, tzinfo=IST), date(2026, 11, 3)),   # just after midnight
    (datetime(2026, 11, 4, 10, 0, tzinfo=IST), date(2026, 11, 4)),
])
def test_the_api_window_reaches_back_across_midnight(tmp_path, now, start):
    url = nse_announcements.URL.format(start, now.date())
    client = FakeClient({url: b"[]"})
    ingest.poll_once(client, tmp_path, feeds=[], now=now)
    assert client.calls == [url]


def test_cli_exit_code_reflects_failures(tmp_path, monkeypatch, capsys, responses):
    monkeypatch.setattr(cli, "now_ist", lambda: SEEN)
    monkeypatch.setattr(ingest, "now_ist", lambda: SEEN)
    monkeypatch.setattr(cli, "Client", lambda: FakeClient(responses))
    assert cli.main(["archive", "--data-dir", str(tmp_path), "--feeds", *FEEDS]) == 0
    out = capsys.readouterr().out
    assert "nse_rss/Online_announcements" in out and "cookies held: 0" in out

    responses[RSS_RESULTS] = Blocked("answered 403")
    assert cli.main(["archive", "--data-dir", str(tmp_path), "--feeds", *FEEDS]) == 1
    assert "ERROR" in capsys.readouterr().out
