import json
from datetime import date, timedelta

import pytest

from conftest import SEEN
from finn.archive import Archive, Record
from finn.times import parse_exchange_time

SOURCE = "nse_api/announcements"


def records(api_items, seen=SEEN):
    """Wrap real API items as Records (key and date as the API source assigns them)."""
    return [Record(SOURCE, it["seq_id"], it, seen, parse_exchange_time(it["sort_date"]), it["sort_date"])
            for it in api_items]


def lines(path):
    return path.read_bytes().splitlines()


def test_new_items_are_written_one_json_line_each(tmp_path, api_items):
    arc = Archive(tmp_path, SOURCE)
    written = arc.add(records(api_items))
    assert len(written) == len(api_items)
    rows = list(arc.rows())
    assert {r["key"] for r in rows} == {it["seq_id"] for it in api_items}
    assert rows[0]["item"] in api_items           # payload stored untouched
    assert rows[0]["published"].endswith("+05:30")


def test_same_items_again_store_nothing_and_leave_files_untouched(tmp_path, api_items):
    arc = Archive(tmp_path, SOURCE)
    arc.add(records(api_items))
    before = {f: f.read_bytes() for f in arc.files()}
    assert arc.add(records(api_items, seen=SEEN + timedelta(minutes=5))) == []
    assert {f: f.read_bytes() for f in arc.files()} == before


def test_dedup_survives_a_restart(tmp_path, api_items):
    Archive(tmp_path, SOURCE).add(records(api_items))
    assert Archive(tmp_path, SOURCE).add(records(api_items)) == []


def test_duplicates_inside_one_batch_are_stored_once(tmp_path, api_items):
    arc = Archive(tmp_path, SOURCE)
    batch = records(api_items[:3]) + records(api_items[:3])
    assert len(arc.add(batch)) == 3
    assert sum(len(lines(f)) for f in arc.files()) == 3


def test_files_are_partitioned_by_exchange_date(tmp_path, api_items):
    arc = Archive(tmp_path, SOURCE)
    arc.add(records(api_items))
    days = {parse_exchange_time(it["sort_date"]).date() for it in api_items}
    assert {f.stem for f in arc.files()} == {f"{d:%Y-%m-%d}" for d in days}


def test_undated_items_go_to_the_day_first_seen(tmp_path, api_items):
    item = api_items[0]
    rec = Record(SOURCE, item["seq_id"], item, SEEN, None, "")
    arc = Archive(tmp_path, SOURCE)
    arc.add([rec])
    assert arc.files() == [arc.path(date(2026, 11, 3))]


def test_lines_within_a_day_are_in_time_order(tmp_path, api_items):
    arc = Archive(tmp_path, SOURCE)
    arc.add(records(api_items))  # the API serves newest first
    for f in arc.files():
        stamps = [json.loads(l)["published"] for l in lines(f)]
        assert stamps == sorted(stamps)


def test_a_line_cut_short_by_a_crash_is_skipped_and_its_item_restored(tmp_path, api_items):
    arc = Archive(tmp_path, SOURCE)
    recs = records(api_items)
    arc.add(recs)
    path = max(arc.files(), key=lambda f: len(lines(f)))
    data = path.read_bytes()
    path.write_bytes(data[: len(data) - 40])  # chop the end off the last line
    lost = json.loads(data.splitlines()[-1])["key"]

    reopened = Archive(tmp_path, SOURCE)
    assert lost not in reopened.keys()
    restored = reopened.add(recs)
    assert [r.key for r in restored] == [lost]

    raw = path.read_bytes().splitlines()
    assert json.loads(raw[-1])["key"] == lost       # appended on a fresh line
    keys = [r["key"] for r in Archive(tmp_path, SOURCE).rows()]
    assert sorted(keys) == sorted(it["seq_id"] for it in api_items)  # garbage skipped, nothing doubled


def test_records_from_another_source_are_rejected(tmp_path, api_items):
    rec = Record("nse_rss/Online_announcements", "x", api_items[0], SEEN)
    with pytest.raises(ValueError):
        Archive(tmp_path, SOURCE).add([rec])
