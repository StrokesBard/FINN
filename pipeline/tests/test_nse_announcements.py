import copy

import pytest

from conftest import SEEN
from finn.archive import Archive
from finn.http import FetchError
from finn.sources import nse_announcements as api


def test_records_are_keyed_by_seq_id_and_dated_by_sort_date(api_items):
    recs = api.parse(api_items, SEEN)
    assert [r.key for r in recs] == [it["seq_id"] for it in api_items]
    for r, it in zip(recs, api_items):
        assert r.published_raw == it["sort_date"]
        assert f"{r.published:%Y-%m-%d %H:%M:%S}" == it["sort_date"]
        assert r.item is it


def test_filings_without_an_attachment_are_kept(api_items):
    # NSE writes "-" when a filing has no attachment.
    bare = [it for it in api_items if it["attchmntFile"] == "-"]
    assert bare
    assert {r.key for r in api.parse(bare, SEEN)} == {it["seq_id"] for it in bare}


def test_filings_either_side_of_midnight_go_to_their_own_day(tmp_path, api_items):
    arc = Archive(tmp_path, api.SOURCE)
    arc.add(api.parse(api_items, SEEN))
    days = sorted({it["sort_date"][:10] for it in api_items})
    assert len(days) >= 2
    assert [f.stem for f in arc.files()] == days


def test_a_filing_edited_upstream_is_not_stored_twice(tmp_path, api_items):
    arc = Archive(tmp_path, api.SOURCE)
    arc.add(api.parse(api_items, SEEN))
    edited = copy.deepcopy(api_items[0])           # same filing, NSE tweaks the summary
    edited["attchmntText"] += " (revised)"
    assert arc.add(api.parse([edited], SEEN)) == []


def test_an_empty_day_is_valid():
    assert api.parse([], SEEN) == []


@pytest.mark.parametrize("payload", [{}, {"data": []}, "Access Denied", [["not", "an", "object"]]])
def test_anything_but_a_list_of_objects_is_an_error(payload):
    with pytest.raises(FetchError):
        api.parse(payload, SEEN)
