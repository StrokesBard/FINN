import pytest

from conftest import SEEN
from finn.archive import Archive
from finn.http import FetchError
from finn.sources import nse_rss


def feed(fixtures, name):
    return (fixtures / "rss" / f"{name}.xml").read_bytes()


def parse(fixtures, name, feed_name=None):
    return nse_rss.parse(feed(fixtures, name), feed_name or name, SEEN)


def test_every_item_becomes_a_record_with_its_raw_fields(fixtures):
    recs = parse(fixtures, "Online_announcements_poll1", "Online_announcements")
    assert len(recs) == feed(fixtures, "Online_announcements_poll1").count(b"<item>")
    r = recs[0]
    assert r.source == "nse_rss/Online_announcements"
    assert set(r.item) == {"title", "link", "description", "pubDate"}
    assert "|SUBJECT:" in r.item["description"]   # NSE's subject suffix, kept verbatim
    assert r.published is not None


def test_keys_are_stable_across_parses(fixtures):
    a = parse(fixtures, "Online_announcements_poll1", "Online_announcements")
    b = parse(fixtures, "Online_announcements_poll1", "Online_announcements")
    assert [r.key for r in a] == [r.key for r in b]


def test_items_sharing_one_link_still_get_distinct_keys(fixtures):
    recs = parse(fixtures, "Financial_Results")
    assert len({r.item["link"] for r in recs}) == 1   # every item links to the same page
    assert len({r.key for r in recs}) == len(recs)


def test_undated_items_are_kept_under_the_day_first_seen(fixtures, tmp_path):
    recs = parse(fixtures, "Annual_Reports")
    assert recs and all(r.published is None and r.published_raw == "" for r in recs)
    arc = Archive(tmp_path, recs[0].source)
    assert len(arc.add(recs)) == len(recs)
    assert [f.name for f in arc.files()] == ["2026-11-03.jsonl"]


def test_odd_timestamps_land_in_their_real_day(fixtures, tmp_path):
    recs = parse(fixtures, "Related_Party_Trans")   # includes "21-FEB-2025 15:12.56"
    arc = Archive(tmp_path, recs[0].source)
    arc.add(recs)
    assert [f.stem for f in arc.files()] == sorted(f"{r.published:%Y-%m-%d}" for r in recs)


def test_two_real_polls_store_their_union_exactly_once(fixtures, tmp_path):
    p1 = parse(fixtures, "Online_announcements_poll1", "Online_announcements")
    p2 = parse(fixtures, "Online_announcements_poll2", "Online_announcements")
    k1, k2 = {r.key for r in p1}, {r.key for r in p2}
    assert k1 & k2 and k2 - k1   # the captures really do overlap and add new items

    arc = Archive(tmp_path, p1[0].source)
    assert len(arc.add(p1)) == len(p1)
    assert {r.key for r in arc.add(p2)} == k2 - k1
    assert arc.add(p1 + p2) == []
    assert sorted(r["key"] for r in arc.rows()) == sorted(k1 | k2)


def test_a_feed_that_repeats_items_is_stored_once_per_item(fixtures, tmp_path):
    # InsiderTrading really served 21 items of which only 8 were distinct.
    raw = feed(fixtures, "InsiderTrading")
    recs = parse(fixtures, "InsiderTrading")
    distinct = {r.key for r in recs}
    assert len(recs) == raw.count(b"<item>") > len(distinct)
    assert len(Archive(tmp_path, recs[0].source).add(recs)) == len(distinct)


def test_a_feed_cut_off_mid_item_keeps_its_complete_items(fixtures):
    # Captured while NSE was serving Online_announcements without its closing tags.
    raw = feed(fixtures, "Online_announcements_truncated")
    assert not nse_rss.is_complete(raw)
    recs = parse(fixtures, "Online_announcements_truncated", "Online_announcements")
    assert len(recs) == raw.count(b"</item>") == raw.count(b"<item>") - 1
    assert all(r.item["title"] and r.published for r in recs)


def test_complete_feeds_are_recognised(fixtures):
    for path in (fixtures / "rss").glob("*.xml"):
        if "truncated" not in path.name:
            assert nse_rss.is_complete(path.read_bytes()), path.name


@pytest.mark.parametrize("page", ["www.bseindia.com", "nsearchives.nseindia.com"])
def test_html_instead_of_a_feed_is_an_error_not_an_empty_feed(fixtures, page):
    # Real HTML that hosts serve with a 200 or 404 (BSE's home page, NSE's error page).
    html = (fixtures / "robots" / f"{page}.txt").read_bytes()
    with pytest.raises(FetchError):
        nse_rss.parse(html, "Online_announcements", SEEN)
