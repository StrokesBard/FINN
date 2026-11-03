# Fixtures

Every file here is a real response, captured on 2026-11-03 (IST) by `scripts/capture_fixtures.py`.

- **robots/:** each host's `/robots.txt` exactly as served. `manifest.json` records the HTTP status and content type, since a 404 or an HTML page means something different from a real file.
- **rss/:** NSE RSS feeds, trimmed to a few `<item>` blocks. The blocks are cut out byte-for-byte; nothing inside an item is edited.
  - `Online_announcements_poll1.xml` and `_poll2.xml` are two real polls about a minute apart. They overlap by 10 items, and poll 2 has 5 new ones.
  - `Online_announcements_truncated.xml` comes from a moment when NSE served the feed cut off mid-item: the first five whole items, plus the broken tail exactly as received.
  - `InsiderTrading.xml` is the whole feed: 21 items, only 8 of them distinct.
  - The other feeds were chosen for their quirks: a link shared by every item, empty `pubDate`s, date-only stamps, and `HH:MM.SS` times.
- **api/announcements.json:** real records from NSE's corporate-announcements API, re-serialised with indentation.
- **brief/:** a real slice of 2–3 Nov 2026 for the Brief (`capture_fixtures.py brief`):
  - `announcements.jsonl`: archived filings for eight companies.
  - `classify_cases.json`: one live filing per classification rule.
  - `bhavcopy/`: every daily price file in the look-back, cut down to six symbols. This includes a real 1:1 bonus (MOLDTKPAC) and a split (JSWDULUX) inside the window.
  - `corporate_actions/`: the real corporate-actions records for those symbols.
  - `integrated_filings/`: XBRL listings for MEDANTA (a corporate), SBIN (a bank) and BAJAJFINSV (results announced, XBRL not yet published).
  - `xbrl/`: the XBRL files, trimmed to the facts the Brief reads. Contexts and values are untouched.
  - `pdf_text/`: text the pipeline extracted from real management-change PDFs. These include UPL's board outcome, which profiles its audit firm before the directors.
  - `EQUITY_L.csv`: NSE's symbol master, cut to the symbols above.
- **llm/:** extracted text and NSE records of real filings, for the model-reading tests (`capture_fixtures.py llm`):
  - ITC's Sproutlife merger letter. pypdf reads its "2026" as "202 6".
  - HDFC Bank's superannuation letter, which uses a curly apostrophe.
  - Two Trent filings that attach the same PDF.

  The model's answers in those tests are written per case; only the documents are captured.

Git stores these with `-text` (see `.gitattributes`), so line endings never change.
