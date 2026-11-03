# FINN

FINN is a mobile-first investor agent. This repository builds its **push** side, **the Brief**: a short, ranked, explained list of what changed across a portfolio of NSE companies in the last 24 hours, 3 days or 7 days. The Brief ends; you mark each card done.

Every number on the screen comes from a primary source (NSE filings, NSE's daily price files, NSE's structured XBRL results), and each card links to those sources. The **pull** side, an on-demand research **Dossier** grounded in annual reports and earnings-call transcripts, is not built yet.

## Try it

| | |
|---|---|
| **Live app**, in any phone browser | https://finn-eight-zeta.vercel.app |
| **Android app** (APK, 1 MB) | https://github.com/StrokesBard/FINN/releases/download/v1.0/FINN.apk |

<p>
  <img src="docs/qr-app.png" width="150" alt="QR code for https://finn-eight-zeta.vercel.app">
  &nbsp;&nbsp;
  <img src="docs/qr-apk.png" width="150" alt="QR code for the Android APK download">
</p>

Scan with the phone's camera: the left code opens the live app, the right one downloads the Android app.

**Installing the APK on Android:**
1. Open the APK link on the phone and download `FINN.apk`.
2. Open the downloaded file. If Android asks, allow your browser to install apps ("Allow from this source"), then go back.
3. Tap **Install**. Play Protect may warn that it doesn't recognise the developer; tap **More details → Install anyway**.

The app opens the live site full screen, so it always shows the current Brief and works offline with the last Brief it loaded. On an iPhone, open the live link in Safari and use **Share → Add to Home Screen**.

## What the screen shows

- **Window:** 24 hours, 3 days or 7 days. The page shows the exact start and end time in IST, and when it was built.
- **Tally:** how many cards *need you*, how many are *worth knowing*, and how many routine filings were hidden. Below it, what was checked: filings, companies, price sessions, and your thresholds.
- **Needs you:** results, unusual price or volume moves, top-level management changes, M&A, litigation, fund raises, pledging, rating downgrades. Each card shows:
  - **Results:** Revenue / EBITDA / PBT / PAT for the quarter, with QoQ and YoY, from the company's XBRL filing. Banks and NBFCs get their own metrics, since EBITDA doesn't apply to lenders.
  - **Unusual moves:** NSE's close against the previous close, and volume against the average of the previous 20 daily files.
  - **Management changes:** the appointee's "Brief profile", quoted from the filing itself.
  - **Why it's here:** the rule that placed the card, the NSE text it matched, and why the card is ranked where it is.
  - **Sources:** every filing PDF, XBRL file and price file the card used.
  - **Done / Undo:** marks a card as handled. The choice is kept on the device, and the Brief says "All clear" when everything is done.
- **Worth knowing:** orders, dividends, transcripts, smaller people changes, and anything no rule recognised. Unknown filings are shown, never buried.
- **Routine, hidden:** a receipt of everything left out, grouped by reason, with links.
- **How this Brief ranks, and How AI is used:** the rules, the category order, the model routing and what it has cost.

Light and dark mode follow the system, and the button at the top right switches between them.

## Architecture

```
NSE (plain HTTP, honest User-Agent, robots.txt checked, no cookies)
 │
 │  finn archive   polls the feeds that keep no history (RSS) and the announcements API
 │  finn collect   portfolio filings, daily price files, corporate actions, XBRL results, filing PDFs
 ▼
data/raw/      append-only JSON lines, one file per source per day, each item stored once
data/cache/    files exactly as published (zip, XML, PDF) plus extracted PDF text
 │
 │  finn enrich    optional: a model reads the PDFs that NSE's summaries don't describe (needs a key)
 │  finn brief     pure, no network: classify, group, rank, enrich, explain
 ▼
data/brief/brief-<24h|3d|7d>.json     exactly what the screen needs, with a source URL for every figure
 │
 ▼
web/           Next.js 16 server components read that JSON; the UI computes nothing
```

| Module | Role |
|---|---|
| `pipeline/src/finn/http.py` | The one place network rules are enforced: robots.txt matching (RFC 9309, with wildcards), refused cookies, retries, conditional GET |
| `pipeline/src/finn/archive.py` | Append-only JSONL archive; deduplicates across restarts; survives a half-written line |
| `pipeline/src/finn/sources/` | NSE RSS feeds and the announcements API |
| `pipeline/src/finn/brief/collect.py` | `finn collect`: fetches and caches everything the Brief reads |
| `pipeline/src/finn/brief/classify.py` | Rules over NSE's own subject line and summary → category, tier, reason, evidence |
| `pipeline/src/finn/brief/prices.py` | Daily moves from the bhavcopy; volume against 20 earlier files; bonus/split caveats |
| `pipeline/src/finn/brief/results.py` | XBRL → headline metrics for corporates, banks and NBFCs; QoQ / YoY |
| `pipeline/src/finn/brief/profile.py` | Appointee profile and stated role, quoted from the filing |
| `pipeline/src/finn/brief/build.py` | `finn brief`: groups a company's filings, folds its price moves into its card, ranks, explains |
| `pipeline/src/finn/llm/` | Optional model reading: routing, schemas, quote verification, cache, cost ledger |
| `web/` | The screen. `lib/brief.ts` loads the JSON; `components/` renders cards, sources, AI blocks, triage |
| `pipeline/scripts/verify_brief.py` | Re-derives every figure on the rendered page from its source files, independently of the pipeline |

Design rules:

- **Rules decide every label and every rank,** so each card can say exactly why it is where it is.
- **Nothing is dropped silently.** Every filing in the window is on a card or in the routine receipt.
- **The build is deterministic.** `finn brief` reads only local files, so the same inputs always give the same screen.

## Where AI is used, and why

Only where rules and parsing can't reach: text that exists only inside a filing PDF.

| Task | Model | Why a model | Safeguards |
|---|---|---|---|
| **Filing digest:** what a filing with an empty NSE summary ("Amalgamation/Merger", "General Updates") discloses | Claude Haiku 5.5, low effort | The substance is prose inside the PDF | Strict JSON schema. Every claim must quote the PDF; a quote not found in the document text discards the claim. Numbers stated in a claim must appear in its quote. |
| **People change:** who joined or left, which role, when and why | Claude Haiku 5.5, low effort | NSE summaries often say only "change in Management" | The quote must contain the person's name, the role as written, and the kind of change claimed. A card is promoted to "Needs you" only if the existing top-role rule matches the verified quote. |
| *Reasoning (reserved):* management's guidance against delivered results | Claude Opus 5.5, with server-side refusal fallback | The only real reasoning task; it belongs to the Dossier | Not used by the Brief |

What a model is **not** used for:
- labels and ranking (rules keep them explainable and repeatable)
- XBRL figures and price moves (already exact)
- appointee profiles (a verbatim quote beats a paraphrase)
- explaining why a stock moved (no primary source exists for that)

The safeguards in practice:
- **Unverified output never reaches the page.** Discarded claims are counted, and every shown claim has its quote one tap away.
- **Each document is sent once,** and the result is cached.
- **Every call's tokens and cost are logged** to `data/llm/usage.jsonl`. The page shows the total.
- **With no API key the app works unchanged** and says "AI off".

## Data sources

All primary and public. The choices behind them are documented in [spike/FINDINGS.md](spike/FINDINGS.md).

| Source | Used for | History |
|---|---|---|
| [NSE corporate announcements API](https://www.nseindia.com/companies-listing/corporate-filings-announcements) | Filings, with symbol, ISIN and attachment | Back to 2004 (undocumented API) |
| [NSE RSS feeds](https://www.nseindia.com/rss-feed) | Filings, archived continuously | Today only, so FINN archives them |
| [NSE daily bhavcopy](https://www.nseindia.com/all-reports) (`nsearchives.nseindia.com`) | Close, previous close, volume | From July 2024 in this format |
| NSE corporate actions API | Bonus and split ex-dates | 20 most recent per company |
| [NSE integrated filings (XBRL)](https://www.nseindia.com/companies-listing/corporate-integrated-filing) | Quarterly results figures | From March 2025 |
| Filing PDFs on `nsearchives.nseindia.com` | Appointee profiles; model reading | As filed |
| `EQUITY_L.csv` | Symbol check and company names | Current |

Not used:
- **Yahoo Finance / yfinance:** robots.txt disallows its API hosts.
- **screener.in:** its terms forbid copying or public display.
- **BSE's API:** returns 403 to plain clients.
- **LinkedIn:** robots.txt disallows everything.

## Run it locally

Tested on Windows 11 with Python 3.12 (also 3.15) and Node 26 (Next.js needs 20.9 or later). The commands below are for Git Bash, from the repo root.

**1. Python pipeline.** Keep the virtualenv outside OneDrive or any synced folder:

```bash
py -3.12 -m venv "$LOCALAPPDATA/finn/venv"
"$LOCALAPPDATA/finn/venv/Scripts/python" -m pip install -e "./pipeline[dev]"
```

On macOS or Linux, use `python3 -m venv .venv` and `.venv/bin/python` instead.

**2. Web app dependencies:**

```bash
npm --prefix web ci
```

**3. Fetch the data.** This takes about 2 minutes and is polite to NSE (one request per second per host):

```bash
"$LOCALAPPDATA/finn/venv/Scripts/python" -m finn collect
```

The portfolio and thresholds live in [config/portfolio.json](config/portfolio.json).

**4. Optional: model reading.** Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` in your editor (`.env` is gitignored). Then:

```bash
"$LOCALAPPDATA/finn/venv/Scripts/python" -m finn enrich
```

Skip this step and the app works without AI, and says so.

**5. Build the Brief:**

```bash
"$LOCALAPPDATA/finn/venv/Scripts/python" -m finn brief
```

**6. Start the app** at http://localhost:3000:

```bash
npm --prefix web run dev
```

**On a phone on the same Wi-Fi,** run the production server, which listens on every network interface:

```bash
npm --prefix web run build && npm --prefix web run start
```

Then open `http://<this PC's IPv4 address>:3000` on the phone. Find the address with `ipconfig`, under your Wi-Fi adapter. If Windows asks, allow Node.js on **private** networks. If your Wi-Fi is set to *Public* in Windows, change it to *Private*, or the firewall blocks the phone. The dev server is not suitable for this: Next.js blocks its development assets for other devices unless they are listed in `allowedDevOrigins`.

To refresh later, run steps 3 to 5 again and reload the page. To keep the history-less feeds archived, leave `python -m finn archive --every 300` running.

## How it's deployed

```
GitHub Action (weekdays 18:00 IST)  finn archive → collect → enrich → brief
 │  pushes brief/*.json to the `data` branch (downloads and the archive stay in the Actions cache)
 ▼
raw.githubusercontent.com/StrokesBard/FINN/data/brief/brief-<window>.json
 │  read at request time, cached for minutes
 ▼
Vercel (Next.js, root directory `web`)  →  https://finn-eight-zeta.vercel.app  →  Android app (PWABuilder)
```

- **Workflow:** [.github/workflows/data.yml](.github/workflows/data.yml). Run it by hand from the Actions tab. Model reading turns on only if the repository has an `ANTHROPIC_API_KEY` secret.
- **Vercel:** import the repo, set **Root Directory** to `web`, and keep everything else at its default. No environment variables are needed: on Vercel the app reads the data branch. Set `FINN_BRIEF_URL` to read from elsewhere. Pushes to the `data` branch don't trigger a deploy ([web/vercel.json](web/vercel.json)).
- **Phone:** [web/app/manifest.ts](web/app/manifest.ts) and the icons make the site installable, and [web/public/sw.js](web/public/sw.js) keeps the last Brief readable offline. The Android app was packaged with [PWABuilder](https://www.pwabuilder.com); [web/public/.well-known/assetlinks.json](web/public/.well-known/assetlinks.json) proves the site and the app belong together, so it opens without a browser bar. The signing key is kept outside the repository.

## Checks

```bash
cd pipeline && "$LOCALAPPDATA/finn/venv/Scripts/python" -m pytest     # 203 tests on real captured data, no key needed
```
```bash
cd pipeline && "$LOCALAPPDATA/finn/venv/Scripts/python" -m ruff check .
```
```bash
cd web && npx tsc --noEmit && npx eslint . --max-warnings=0
```
```bash
"$LOCALAPPDATA/finn/venv/Scripts/python" pipeline/scripts/verify_brief.py --links   # with the app running
```

The last check reads the rendered page for every window and re-derives each figure and label from the source files it links:
- XBRL, re-parsed by regex
- prices, re-read from the bhavcopy CSVs
- profiles and model quotes, re-read with pdfplumber

It then checks that every link answers HTTP 200.

Test fixtures are real responses captured on 2026-11-03 (see [pipeline/tests/fixtures/README.md](pipeline/tests/fixtures/README.md)). Refresh them with `python pipeline/scripts/capture_fixtures.py`.

## Layout

```
config/            portfolio and alert thresholds
pipeline/          Python package `finn`: sources, archive, collect, the Brief, model reading
  tests/           tests on real captured exchange data (tests/fixtures/)
  scripts/         fixture capture, screen verification
web/               Next.js 16 app (the Brief screen)
spike/             the scripts that proved each data source, and FINDINGS.md
docs/              QR codes for "Try it"
data/              everything the pipeline writes; git-ignored on main (see below)
```

## Known limits

- **No Dossier yet.** The pull side (annual reports, transcripts, promised vs delivered) is not built.
- **The scheduled refresh hasn't been proven yet.** NSE's announcements API is undocumented, and whether it answers GitHub's servers is untested. Until the workflow runs green, the live Brief stays at the snapshot published from this PC on 3 Nov 2026 (steps 3 to 5, then a push to the `data` branch).
- **The corporate-actions API returns at most 20 rows per company.**
- **Model reading is untested against real API calls.** It's tested without a key using stand-in replies, so the share of claims that survive verification is unknown until it runs with a key.

## Data is kept off `main`

`data/` is ignored on `main`, so the code history stays readable. When the archive is worth committing, it gets its own orphan branch, checked out as a worktree at `data/`:

```bash
mv data data.tmp                        # the worktree needs an empty path
git worktree add --orphan -b data data
cp -r data.tmp/. data/ && rm -r data.tmp
```

The pipeline keeps writing to `data/` as usual. Snapshots are committed from inside `data/` to the `data` branch, which shares no history with `main`.
