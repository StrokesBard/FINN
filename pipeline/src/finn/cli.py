"""finn archive: poll NSE's history-less sources and append what is new.

    finn archive                    one pass, exit 1 if any source failed
    finn archive --every 300        keep polling every 5 minutes
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

from finn.http import Client
from finn.ingest import poll_once
from finn.sources.nse_rss import FEEDS
from finn.times import now_ist


def _report(results, data_dir):
    print(f"{now_ist():%Y-%m-%d %H:%M:%S} IST")
    for r in results:
        if r.error:
            status = f"ERROR {r.error}"
        elif r.unchanged:
            status = "unchanged (304)"
        else:
            status = ", ".join(str(f.relative_to(data_dir)) for f in r.files) or "-"
        if r.note:
            status += f"  [{r.note}]"
        print(f"  {r.source:<36} fetched {r.fetched:>5}  new {r.new:>5}  {status}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="finn")
    sub = parser.add_subparsers(dest="command", required=True)
    arc = sub.add_parser("archive", help="poll the history-less sources and append new items")
    arc.add_argument("--data-dir", type=Path, default=Path(os.environ.get("FINN_DATA_DIR", "data")),
                     help="archive root (default: $FINN_DATA_DIR or ./data)")
    arc.add_argument("--every", type=int, metavar="SECONDS", help="keep polling at this interval")
    arc.add_argument("--feeds", nargs="+", default=list(FEEDS), metavar="FEED", help="RSS feeds to poll")
    arc.add_argument("--no-api", action="store_true", help="skip the announcements API")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    client = Client()
    data_dir = args.data_dir.resolve()
    try:
        while True:
            results = poll_once(client, data_dir, feeds=args.feeds, api=not args.no_api)
            _report(results, data_dir)
            print(f"  cookies held: {len(client.session.cookies)}")
            if not args.every:
                return 1 if any(r.error for r in results) else 0
            time.sleep(args.every)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
