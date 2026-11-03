# Fixtures

Every file here is a real response, captured on 2026-11-03 (IST) by `scripts/capture_fixtures.py`.

- **robots/:** each host's `/robots.txt` exactly as served. `manifest.json` records the HTTP status and content type, since a 404 or an HTML page means something different from a real file.
- **rss/:** NSE RSS feeds, trimmed to a few `<item>` blocks. The blocks are cut out byte-for-byte; nothing inside an item is edited.
  - `Online_announcements_poll1.xml` and `_poll2.xml` are two real polls about a minute apart. They overlap by 10 items, and poll 2 has 5 new ones.
  - `Online_announcements_truncated.xml` comes from a moment when NSE served the feed cut off mid-item: the first five whole items, plus the broken tail exactly as received.
  - `InsiderTrading.xml` is the whole feed: 21 items, only 8 of them distinct.
  - The other feeds were chosen for their quirks: a link shared by every item, empty `pubDate`s, date-only stamps, and `HH:MM.SS` times.
- **api/announcements.json:** real records from NSE's corporate-announcements API, re-serialised with indentation.

Git stores these with `-text` (see `.gitattributes`), so line endings never change.
