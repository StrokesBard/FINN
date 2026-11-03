"""The finn command line.

    finn archive [--every N]   poll NSE's history-less feeds and append what is new (exit 1 if a source failed)
    finn collect               fetch and cache what the Brief needs for the portfolio
    finn brief                 build data/brief/brief-<window>.json from local files only
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


def _collect(args):
    from finn.brief.collect import collect, load_portfolio
    report = collect(Client(), args.data_dir, load_portfolio(args.portfolio), now_ist())
    for name, ok, detail in report:
        print(f"  {'ok ' if ok else 'ERR'} {name:<34} {detail}")
    return 0 if all(ok for _, ok, _ in report) else 1


def _brief(args):
    import json

    from finn.brief.build import WINDOWS, build
    from finn.brief.collect import load_portfolio
    portfolio, now = load_portfolio(args.portfolio), now_ist()
    out = args.data_dir / "brief"
    out.mkdir(parents=True, exist_ok=True)
    for key in WINDOWS:
        brief = build(args.data_dir, portfolio, now, key)
        path = out / f"brief-{key}.json"
        path.write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
        c = brief["counts"]
        print(f"  {path}: {c['needs_you']} need you, {c['worth_knowing']} worth knowing, "
              f"{c['routine_filings']} routine hidden ({c['filings']} filings)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="finn")
    sub = parser.add_subparsers(dest="command", required=True)
    arc = sub.add_parser("archive", help="poll the history-less sources and append new items")
    arc.add_argument("--data-dir", type=Path, default=Path(os.environ.get("FINN_DATA_DIR", "data")),
                     help="archive root (default: $FINN_DATA_DIR or ./data)")
    arc.add_argument("--every", type=int, metavar="SECONDS", help="keep polling at this interval")
    arc.add_argument("--feeds", nargs="+", default=list(FEEDS), metavar="FEED", help="RSS feeds to poll")
    arc.add_argument("--no-api", action="store_true", help="skip the announcements API")
    for name, text in (("collect", "fetch and cache what the Brief needs for the portfolio"),
                       ("brief", "build the Brief JSON for every window from local data")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--data-dir", type=Path, default=Path(os.environ.get("FINN_DATA_DIR", "data")))
        p.add_argument("--portfolio", type=Path, default=Path("config/portfolio.json"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "collect":
        return _collect(args)
    if args.command == "brief":
        return _brief(args)
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
