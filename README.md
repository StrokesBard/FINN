# FINN

A mobile-first investor agent: a short daily **Brief** of what changed across a portfolio (push), and an on-demand **Dossier** grounded in each company's own filings (pull).

## Layout

```
pipeline/          Python: ingestion, parsing, storage (installable package `finn`)
  src/finn/
  tests/           tests run against real captured exchange data (tests/fixtures/)
web/               the mobile web app (not started yet)
spike/             throwaway scripts that proved each data source; see spike/FINDINGS.md
data/              local archive written by the pipeline; git-ignored on main
```

## Setup

Keep the virtualenv **outside** OneDrive (or any synced folder), or the sync client will fight pip over thousands of files. From the repo root, in Git Bash:

```bash
py -3.12 -m venv "$LOCALAPPDATA/finn/venv"
"$LOCALAPPDATA/finn/venv/Scripts/python" -m pip install -e "./pipeline[dev]"
```

Verified on Windows 11 with Python 3.12 and 3.15.

## Archiving the feeds that have no history

NSE's RSS feeds hold only today's filings (or their last ~20 items). Anything not archived the same day is gone, so these are polled continuously. The announcements API is archived alongside them: it does have history, but it's undocumented, and archiving records when FINN first saw each filing.

```bash
python -m finn archive              # one pass; exit code 1 if any source failed
python -m finn archive --every 300  # keep polling every 5 minutes
```

Each item is written once to `data/raw/<source>/<YYYY-MM-DD>.jsonl`, under its exchange date in IST. Every line has the same shape:

```json
{"key": "...", "published": "2026-11-03T16:36:31+05:30", "first_seen": "...", "source": "nse_rss/Online_announcements", "published_raw": "03-Nov-2026 16:36:31", "item": {"...": "the payload exactly as NSE sent it"}}
```

Run it from the repo root, or set `FINN_DATA_DIR`. One archiver per data directory at a time.

## Tests

```bash
cd pipeline && python -m pytest
```

Fixtures are real NSE, BSE, Yahoo and screener responses captured on 2026-11-03 (see `pipeline/tests/fixtures/README.md`). Refresh them with `python scripts/capture_fixtures.py`.

## Data is kept off `main`

`data/` is ignored on `main`, so the code history stays readable. When the archive is worth committing, it gets its own orphan branch, checked out as a worktree at `data/`:

```bash
mv data data.tmp                        # the worktree needs an empty path
git worktree add --orphan -b data data
cp -r data.tmp/. data/ && rm -r data.tmp
```

The pipeline keeps writing to `data/` as usual. Snapshots are committed from inside `data/` to the `data` branch, which shares no history with `main`.
