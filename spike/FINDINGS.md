# FINN data-source spike: findings

Run on **2026-11-03 (Tue)** from a home connection in India, Windows 11, Python 3.15.2.
Every request was made with plain `requests`, an honest User-Agent (`finn-spike/0.1 …`), no cookies, no browser headers, and a `robots.txt` check before each fetch (see [_common.py](_common.py)).
The feeds returned filings timestamped the same afternoon, so the data is live.

## TL;DR

Every input The Brief needs is available from **NSE itself**, with plain HTTP and within robots.txt.
That covers prices, filings, results numbers, annual reports, earnings-call transcripts and the profiles of newly appointed managers.

Two sources the brief suggests are out:
- **Yahoo Finance / yfinance.** robots.txt disallows everything on the API hosts.
- **screener.in.** Its terms forbid copying or publicly displaying its material.

Neither is needed. The biggest open risk is that NSE's JSON API is unofficial, and it hasn't been tested from a cloud server's IP address yet.

## Verdict table

| Need | Source | Works? | History | Format | Verdict |
|---|---|---|---|---|---|
| EOD price & volume | Yahoo chart API (yfinance) | Not called: `query1/query2.finance.yahoo.com/robots.txt` is `Disallow: /` | – | – | ❌ **Excluded** |
| EOD price & volume | NSE CM bhavcopy, UDiFF format (`nsearchives`) | ✅ 200 | 8 Jul 2024 → today | zipped CSV, whole market per day, ~200 KB | ✅ **Primary** |
| EOD (pre-Jul 2024) | NSE legacy bhavcopy | ✅ 200 | to 5 Jul 2024, back to at least 2020 | zipped CSV, different schema | ✅ only if we need >16 months |
| Delivery % | NSE `sec_bhavdata_full` | ✅ 200 | not probed | CSV | ✅ optional signal |
| EOD backup | BSE UDiFF bhavcopy (`www.bseindia.com/download`) | ✅ 200 | not probed | CSV, same schema as NSE | ✅ backup + BSE code map |
| Split/bonus adjustment | NSE `/api/corporates-corporateActions` | ✅ 200 | 20 rows returned (cap?) | JSON | ✅ |
| Announcements | NSE `/api/corporate-announcements` | ✅ 12/12 calls, no cookies | per symbol back to 2004; date-range queries | JSON + PDF/XML attachment links | ✅ **Primary** (unofficial) |
| Announcements | NSE RSS (23 feeds, `nsearchives/content/RSS`) | ✅ 200 | **today only** (main feed) or last 20 items | RSS 2.0 | ✅ fallback; must archive |
| Announcements | BSE API (`api.bseindia.com`) | ❌ 403 Akamai, even for robots.txt | – | – | ❌ |
| Announcements | BSE RSS | Only exchange notices and the SENSEX feed; no company filings | – | – | ❌ |
| Results numbers | NSE `/api/corporates-financial-results` (legacy XBRL) | ✅ 200 | Mar 2005 → **Dec 2024 only** | XBRL | ✅ history |
| Results numbers | NSE `/api/integrated-filing-results` (Integrated Filing - Financials) | ✅ 200 | Mar 2025 → today | XBRL, 1–2 MB | ✅ **Primary** |
| Results numbers, first hours | Results PDF attached to the announcement | ✅ all text PDFs | – | PDF, 1–27 MB | ✅ fallback while XBRL lags |
| Annual reports | NSE `/api/annual-reports` | ✅ 200 | INFY 17 yrs, HDFCBANK 18, IRCTC 7 | PDF, 9–30 MB, 380–680 pages, text | ✅ **Primary** |
| Concall transcripts | NSE announcements filtered on "transcript" | ✅ | INFY 35, HDFCBANK 20, IRCTC 20 filings | PDF, text | ✅ **Primary** |
| Document index + tables | screener.in `/company/<SYM>/consolidated/` | ✅ 200, robots allows `/company/` | 15 ARs, 50+ concall links | HTML | ⚠️ **Terms forbid it**, reference only |
| Ticker master | NSE `EQUITY_L.csv` | ✅ 200 | current | CSV, 2,623 rows with ISIN | ✅ |
| Renames | NSE `namechange.csv` | ✅ 200 (`symchange.csv` is 404) | 2,344 rows | CSV | ✅ |
| Appointee bio | "Brief profile" section inside the filing | ✅ **8/8** sampled appointment filings | – | PDF text | ✅ **Primary** |
| Appointee bio | LinkedIn | ❌ robots.txt `User-agent: * / Disallow: /` | – | – | ❌ |
| Bio enrichment | A web-search API | Not tested (needs an API key) | – | – | ⏸ optional |

## Recommended source stack for The Brief

- **Prices:** NSE UDiFF bhavcopy, fetched daily around 17:00 IST, adjusted with NSE corporate actions. The BSE bhavcopy is the fallback.
- **Filings feed:** poll the NSE announcements API by date range every ~5 minutes in market hours and store everything. Keep the RSS feed as a fallback, since it only holds today.
- **Results card:** use the Integrated Filing XBRL for the quarter, the previous quarter and the same quarter last year. Until the XBRL appears (2–4 hours later), show the results PDF with "numbers pending".
- **Dossier:** annual reports from the NSE AR API, plus transcripts from NSE announcements, plus 8–10 quarters of XBRL for trajectory and cash flow.
- **Management card:** the "Brief profile" paragraph from the filing itself, which is primary and needs no LinkedIn.
- **Identity:** use ISIN as the stable key; symbols change. Map names via `EQUITY_L.csv` and BSE codes via the BSE bhavcopy's ISIN column.

## Per-source detail

### 1. EOD prices: [01_eod_prices.py](01_eod_prices.py)

- **Client:** `requests`, honest UA, no other headers.
- **URL:** `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`.
- **robots:** `nsearchives` has no robots.txt (404), so no rules apply.
- **Publish time:** Last-Modified for 2 Nov was 11:03 GMT, i.e. **16:33 IST**. Before then today's file returns 404.
- **Schema:** 34 columns, including `TckrSymb`, `ISIN`, `SctySrs`, `OpnPric`, `HghPric`, `LwPric`, `ClsPric`, `PrvsClsgPric` and `TtlTradgVol`. The file includes the previous close, so a daily % move needs no second file.
- **Sample, 2 Nov 2026:** RELIANCE closed ₹1,300.00 against ₹1,164.90 (**+11.6%**) on 88.1M shares. That is exactly the kind of unusual move the alerts should catch, and a good demo case.
- **History:** UDiFF files exist from 8 Jul 2024. Older days use the legacy `content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip`, which has a different schema.
  - A 20-day volume average needs ~30 files (~6 MB).
  - A 90-day threshold backtest needs ~65 files (~13 MB).
- **BSE bhavcopy:** same UDiFF schema. `FinInstrmId` is the BSE scrip code (e.g. 500325 = Reliance). BSE volumes are a small fraction of NSE's, so NSE should drive volume alerts.

### 2. Announcements: [02_announcements.py](02_announcements.py)

- **NSE API:** `https://www.nseindia.com/api/corporate-announcements?index=equities[&symbol=X][&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY]`.
  - It works with a plain request and no cookies, although `www.nseindia.com/` (the homepage) returns **403** to the same client. NSE's bot rules are selective and could change.
  - Fields: `symbol`, `sm_isin`, `sm_name`, `smIndustry`, `desc` (NSE's subject), `attchmntText` (one-line summary), `attchmntFile`, `an_dt`, `seq_id` (a good dedupe key) and `hasXbrl`.
  - The whole market is about 900 filings per trading day (5,486 over 26 Oct – 2 Nov).
- **RSS:** the index at `https://www.nseindia.com/rss-feed` lists 23 feeds. `Online_announcements.xml` held 1,043 items, all from today (00:00 → 16:02). Each item has the company name, link, `published` time, and a description ending in `|SUBJECT: …`. **There is no symbol or ISIN in the RSS**, so items have to be matched by company name or by the symbol prefix in the attachment filename.
- **Subject vocabulary:** NSE's `desc` is coarse. Across INFY's history, "Press Release" appears 993 times and "Updates" 792 times. These are catch-alls, so the classifier has to read `attchmntText` too, not just `desc`.
- **Volume and noise:** in the RSS, 419 of 1,043 items were mutual-fund "Declaration of NAV". Drop them up front.
- **BSE:** the API returns 403 (Akamai) to a plain client, so it wasn't pursued under the no-workarounds rule. That's fine: the brief scopes research to NSE tickers.

### 3. Results numbers: [03_results.py](03_results.py)

- **Two listings, split by date:** the legacy results endpoint stops at the **Dec-2024** quarter. Everything since Mar-2025 is under `/api/integrated-filing-results?index=equities&symbol=X&type=Integrated%20Filing-%20Financials`. Code has to merge both to get 8+ quarters.
- **Output check.** The latest quarter is Sep-2026 (Q2 FY27), consolidated, ₹ crore, computed from XBRL:

  | Company | Type | Revenue | EBITDA* | PBT | PAT | QoQ / YoY (PAT) |
  |---|---|---|---|---|---|---|
  | INFY | corporate | 49,244 | 11,689 | 11,063 | 7,838 | +0.8% / +6.3% |
  | RELIANCE | corporate | 3,32,861 | 56,616 | 38,613 | 29,550 | +27.4% / +33.8% |
  | HDFCBANK | bank | NII 44,464 · PPOP 32,872 | n/a | 27,826 | 20,700 | +1.6% / +5.6% |
  | BAJFINANCE | NBFC | NII 13,335 · credit cost 2,166 | n/a | 8,534 | 6,367 | +4.7% / +28.7% |
  | IRCTC | corporate | Jun-2026 is latest; **Sep-2026 not filed yet** | | | | |

  *EBITDA = PBT + finance costs + D&A − other income.

  As a cross-check, INFY Sep-2025 profit attributable to owners comes out at ₹7,364 cr, which matches Infosys's publicly reported Q2 FY26 net profit.
- **Lag:** the XBRL appears **2–4 hours after the results PDF**. INFY's PDF went out at 16:08 and the XBRL at 20:16. For RELIANCE it was 19:40 → 21:32, for HDFCBANK 13:56 → 17:47, and for BAJFINANCE 17:20 → 19:59.
- **PDFs:** all sampled results PDFs are text, not scans. Sizes vary widely: INFY's outcome PDF is 195 pages / 26.7 MB because it bundles IFRS statements and press material.

### 4. Fundamentals: [04_fundamentals.py](04_fundamentals.py)

- **Annual reports:** `/api/annual-reports?index=equities&symbol=X` returns `fromYr`, `toYr`, `submission_type` (New/Revised) and a `fileName` URL on `nsearchives`.
- **Transcripts:** filter NSE announcements where `attchmntText` contains "transcript". The results also include AGM, press-conference and "AI Day" transcripts, so match on "earnings"/"con call", or by date proximity to results. The file is byte-identical to the BSE copy screener links to.
- **Transcript lag:** about 5–6 days after the call. HDFCBANK's call was on 17 Oct and the transcript was filed 23 Oct; INFY's results came out 23 Oct and the transcript 28 Oct. The newest quarter's promise-vs-delivered check therefore waits about a week.
- **Size and speed** (from [06_cross_checks.py](06_cross_checks.py)):

  | Document | Pages | Tokens (approx.) | pypdf | pdfplumber |
  |---|---|---|---|---|
  | HDFCBANK transcript | 17 | ~13.6k | 2.5 s | ~4.9 s |
  | INFY annual report | 384 | **~327k** | **41.5 s** | ~167 s |

  A whole annual report is too slow and too expensive to process on demand. Extract text per page once, cache it, and send only the targeted sections (MD&A, statements, notes, cash flow) to a model.
- **screener.in:** technically works, and robots.txt allows `/company/…`. But its [terms](https://www.screener.in/guides/terms/) grant use for "personal, non-commercial transitory viewing only" and forbid copying the material or displaying it publicly. Its document links all point to BSE/NSE PDFs that we can already get directly from NSE, so it is not needed.

### 5. Tickers and bios: [05_tickers_and_bios.py](05_tickers_and_bios.py)

- **`EQUITY_L.csv`:** 2,623 rows (EQ 2,391, BE 199, BZ 33), with name, ISIN and listing date.
  - Substring search works for user lookup, but some queries are ambiguous. "Infosys" also matches HCL Infosystems, "Tata Motors" returns both TMCV and TMPV, and "reliance" returns four companies. The UI needs a picker.
- **Symbol changes:** `TATAMOTORS` no longer exists; the demerged companies trade as **TMPV** (old ISIN `INE155A01022`) and **TMCV** (new ISIN). Key everything on ISIN. `namechange.csv` covers renames; `symchange.csv` is 404.
- **BSE codes:** 2,435 of 2,623 NSE symbols match a BSE code via ISIN.
- **Management changes:** 302 change-like filings across all companies in 10 days. All **8 of 8** appointment PDFs sampled had a "Brief profile" paragraph covering experience, prior employers and qualifications (Alkem CEO, CRISIL CTIO, Bata, ESDS and others). SEBI's disclosure rules require it. None of these filings were XBRL, so the text has to be extracted from the PDF.

## Gotchas (each one changes the code we write)

1. **Bank, NBFC and corporate filings use three different XBRL taxonomies.**
   - Banks (`BANKING_…`, non-Ind-AS) report `InterestEarned/Expended`, `OperatingProfitBeforeProvisionAndContingencies` and `ProvisionsOtherThanTaxAndContingencies`.
   - NBFCs (Ind-AS Division III) report `InterestEarned`, `FinanceCosts` and `ImpairmentOnFinancialInstruments`.
   - Detect banks by `InterestExpended`, not `InterestEarned`: the first version of the script misread an NBFC as a bank.
   - EBITDA only exists for corporates. Banks get NII / PPOP / PBT / PAT, and NBFCs get NII / credit cost / PBT / PAT.
2. **"0" can mean "not reported".** Consolidated bank files report `PercentageOfGrossNpa = 0.00`; asset quality only appears in standalone. Treat zero ratios as missing.
3. **Each XBRL file holds only the current quarter and year-to-date.** QoQ and YoY need three filings. In a legacy INFY file, the YTD context (`FourD`) was labelled with the quarter's dates but held 9-month values. Pick the quarter by context id (`OneD`) and sanity-check (YTD ≥ quarter).
4. **Consolidated and standalone are separate filings.** Prefer consolidated, label it, and fall back to standalone. Separately, decide between PAT and **PAT attributable to owners** (`ProfitOrLossAttributableToOwnersOfParent`). Companies quote the second one; INFY's are 7,838 and 7,823.
5. **Revised filings exist** (IRCTC has 2). Keep the latest revision per (quarter, consolidated/standalone).
6. **Late filers are normal.** SEBI allows 45 days after Q1–Q3 and 60 after Q4. On 3 Nov, IRCTC's Sep quarter wasn't filed yet. The UI needs a "not yet reported" state, not a blank.
7. **Our EBITDA won't match every company's own figure.** Some companies (e.g. Reliance) report EBITDA including other income. Show the formula on the card.
8. **Bhavcopy prices are unadjusted.** A 1:1 bonus looks like a 50% crash (HDFCBANK had one with ex-date 26 Aug 2025). Adjust history with the corporate-actions ex-dates before computing moves and averages.
9. **Stocks move between series** (EQ ↔ BE/BZ trade-to-trade). Select by ISIN across series, not `SctySrs == "EQ"`.
10. **The RSS feeds can't be used for history.** The main feed is today only; the others keep the last 20 items. Archive them if we rely on them.
11. **The NSE API is undocumented,** with no SLA and no published rate limit. It worked 12/12 times here, but the 403 on NSE's homepage shows bot rules are in play. Cache aggressively, poll gently, and keep the RSS and static-file fallbacks.
12. **The RSS has no symbol.** Join on company name, or on the symbol prefix in the attachment filename (e.g. `INFY_30102026…pdf`). Prefer the API, which carries both symbol and ISIN.
13. **pypdf 6.x prints "fontTools is required…" warnings** (97 on one annual report) unless `fonttools` is installed. It's now pinned.
14. **OneDrive:** the project sits inside a synced OneDrive folder. Keep virtualenvs and caches **outside** it (the spike venv lives in the session temp folder), or OneDrive will try to sync thousands of files and can lock them during `pip install`.

## Found later, while building the archiver (same day)

These came up running `finn archive` for real and are handled in `pipeline/`:

- **NSE served `Online_announcements.xml` cut off mid-item.** It had 1,207 whole items and no closing `</rss>`, and this lasted several minutes before a complete copy came back. Feeds that don't parse as a whole are salvaged item by item.
- **Feeds repeat items.** `InsiderTrading.xml` had 21 items, of which only 8 were distinct.
- **The RSS feeds support conditional GET** (ETag and Last-Modified), so an unchanged feed costs a 304 with no body. The JSON API sends no validators.
- **`nsearchives` stalled some requests until they timed out.** It happened with some longer User-Agent strings, and also for `robots.txt` itself. We didn't investigate further, because that would mean probing bot defences. The pipeline uses one short honest UA, `finn/0.1 (research prototype)`, and treats timeouts as transient: retry with backoff, then skip until the next poll.
- **`api.bseindia.com/robots.txt` answers differently over time.** Earlier it gave a 403 (Akamai); later it served BSE's HTML home page.
- **Before Python 3.15, `urllib.robotparser` ignores `*` wildcards.** It allows URLs that screener.in's `Disallow: /*?q=` forbids, so `finn.http` has its own RFC 9309 matcher.

## Library and OS notes

- Windows 11 has **Python 3.15.2** (default) and 3.12 installed. All libraries in [requirements.txt](requirements.txt) installed from **binary wheels only** on both (`--only-binary :all:`), so no compiler is needed.
- Verified versions: `requests 2.34.2`, `feedparser 6.0.14`, `lxml 6.1.3`, `pandas 3.1.0`, `numpy 2.5.4`, `pypdf 6.21.4`, `fonttools 4.68.0`, `pdfplumber 0.11.10`.
- **`yfinance` was deliberately not installed,** because its backend is disallowed by robots.txt.
- Git Bash's `pdftotext` (poppler) is available as an OCR-free PDF fallback. `pdftoppm` is not installed, so page rendering isn't available yet.

## Still unverified

| Item | Why it matters | How to close it |
|---|---|---|
| NSE API and `nsearchives` from a **cloud server IP** | Akamai often blocks datacenter IPs; this is the biggest deployment risk | Run `02_announcements.py` and `01_eod_prices.py` on the chosen host before building |
| NSE website terms of use | Couldn't read them: the homepage returns 403 to a plain client, and guessed URLs 404 | Read them manually in a browser |
| NSE API rate limits under polling | Only 12 calls tested | Run a 1-hour poll at a 5-minute interval during market hours |
| **Insurance companies' XBRL** (HDFCLIFE, LICI…) | Likely a fourth taxonomy | Run `03_results.py HDFCLIFE LICI` and inspect the element names |
| Scanned PDFs at small or SME companies | All 10+ PDFs tested were text | Sample 10 small-cap transcripts and appointment letters |
| Corporate-actions history beyond 20 rows | Response may be capped | Probe for `from_date`/`to_date` parameters |
| Trading-holiday calendar | Needed to tell a holiday from a late file | Probe `/api/holiday-master?type=trading`, or treat 404 after 18:00 as a holiday |
| Q4 (March) XBRL structure | Quarter vs annual contexts may differ | Parse one Mar-2026 filing |
| Web-search enrichment for bios | Optional; filings already include profiles | Needs an API key (Brave, Tavily or similar, on a free tier) |

## How to re-run

From the project root, in Git Bash (the venv lives outside OneDrive on purpose):

```bash
py -3.12 -m venv "$LOCALAPPDATA/finn-spike-venv"
"$LOCALAPPDATA/finn-spike-venv/Scripts/python" -m pip install -r spike/requirements.txt
cd spike && PY="$LOCALAPPDATA/finn-spike-venv/Scripts/python"
"$PY" 01_eod_prices.py
"$PY" 02_announcements.py
"$PY" 03_results.py INFY HDFCBANK BAJFINANCE   # any NSE symbols
"$PY" 04_fundamentals.py IRCTC
"$PY" 05_tickers_and_bios.py
"$PY" 06_cross_checks.py
```
