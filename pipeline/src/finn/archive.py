"""Append-only archive: one JSON-lines file per source per day.

    data/raw/<source>/<YYYY-MM-DD>.jsonl

A record lands in the file for its exchange date (IST), or for the day we
first saw it when the item carries no usable date. Each line is

    {"key", "published", "first_seen", "source", "published_raw", "item"}

where `item` is the source payload untouched, so a parsing mistake on our
side never loses data.

No item is stored twice: every key already on disk for the source is loaded
before the first write (a year is a few hundred thousand short strings), and
each batch is deduplicated in memory. Files are only ever appended to; a line
cut short by a crash is skipped on read, and its item is stored again on the
next poll. One writer per source directory is assumed.
"""
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finn.times import IST

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Record:
    source: str
    key: str
    item: dict
    first_seen: datetime
    published: datetime | None = None
    published_raw: str | None = None

    @property
    def day(self):
        return (self.published or self.first_seen).astimezone(IST).date()

    def to_line(self):
        return json.dumps({
            "key": self.key,
            "published": self.published.isoformat() if self.published else None,
            "first_seen": self.first_seen.isoformat(),
            "source": self.source,
            "published_raw": self.published_raw,
            "item": self.item,
        }, ensure_ascii=False)


class Archive:
    def __init__(self, data_dir, source):
        self.source = source
        self.dir = Path(data_dir) / "raw" / source
        self._keys = None

    def path(self, day):
        return self.dir / f"{day:%Y-%m-%d}.jsonl"

    def files(self):
        return sorted(self.dir.glob("*.jsonl"))

    def rows(self, day=None):
        """Yield stored records as dicts, oldest file first."""
        for f in [self.path(day)] if day else self.files():
            if not f.exists():
                continue
            with f.open("rb") as fh:
                for n, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("skipping unreadable line %s:%d (interrupted write?)", f, n)

    def keys(self):
        if self._keys is None:
            self._keys = {row["key"] for row in self.rows()}
        return self._keys

    def add(self, records):
        """Store the records not already archived. Returns the ones written."""
        stored = self.keys()
        fresh, batch = [], set()
        for r in records:
            if r.source != self.source:
                raise ValueError(f"record from {r.source!r} offered to archive {self.source!r}")
            if r.key in stored or r.key in batch:
                continue
            batch.add(r.key)
            fresh.append(r)

        by_day = defaultdict(list)
        for r in sorted(fresh, key=lambda r: r.published or r.first_seen):
            by_day[r.day].append(r)
        for day, rows in sorted(by_day.items()):
            _append(self.path(day), rows)
        stored |= batch  # only after the write succeeded
        return fresh


def _append(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            needs_newline = fh.read(1) != b"\n"  # previous write was cut short
    payload = "".join(r.to_line() + "\n" for r in records).encode("utf-8")
    with path.open("ab") as fh:
        if needs_newline:
            fh.write(b"\n")
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
