"""One polling pass over the sources that must be archived as they happen."""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from finn.archive import Archive
from finn.http import Blocked, FetchError
from finn.sources import nse_announcements, nse_rss
from finn.times import now_ist

log = logging.getLogger(__name__)


@dataclass
class PollResult:
    source: str
    fetched: int = 0
    new: int = 0
    unchanged: bool = False
    error: str | None = None
    note: str | None = None
    files: list = field(default_factory=list)


_archives = {}


def _archive(data_dir, source):
    """One Archive per directory for the life of the process, so a polling loop
    reads the stored keys from disk once, not on every pass."""
    key = (str(data_dir), source)
    if key not in _archives:
        _archives[key] = Archive(data_dir, source)
    return _archives[key]


def _store(archive, records, result):
    fresh = archive.add(records)
    result.fetched, result.new = len(records), len(fresh)
    result.files = [archive.path(d) for d in sorted({r.day for r in fresh})]


def poll_rss(client, data_dir, feed, now):
    result = PollResult(nse_rss.source_name(feed))
    try:
        body = nse_rss.fetch(client, feed)
        if body is None:
            result.unchanged = True
            return result
        _store(_archive(data_dir, result.source), nse_rss.parse(body, feed, now), result)
        if not nse_rss.is_complete(body):
            result.note = "feed was cut off upstream; kept its complete items"
    except (Blocked, FetchError) as e:
        result.error = str(e)
    return result


def poll_announcements(client, data_dir, now):
    """Today's filings; in the first hour after midnight, yesterday's too, so
    anything disseminated just before midnight is not missed."""
    result = PollResult(nse_announcements.SOURCE)
    start = (now - timedelta(hours=1)).date()
    try:
        payload = nse_announcements.fetch(client, start, now.date())
        _store(_archive(data_dir, result.source), nse_announcements.parse(payload, now), result)
    except (Blocked, FetchError) as e:
        result.error = str(e)
    return result


def poll_once(client, data_dir, feeds=nse_rss.FEEDS, api=True, now=None):
    """Poll every source once. One failing source never stops the others."""
    now = now or now_ist()
    results = [poll_rss(client, data_dir, feed, now) for feed in feeds]
    if api:
        results.append(poll_announcements(client, data_dir, now))
    return results
