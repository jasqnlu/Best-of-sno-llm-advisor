# Best of SNO — Historical Backfill (Layer 1) Design

**Status:** Draft for approval
**Date:** 2026-10-29
**Parent design:** `docs/superpowers/specs/2026-10-28-best-of-sno-advisor-design.md` (§5, Layer 1)
**Builds on:** `best_of_sno/scraper.py` (daily scraper, already shipped)

## 1. Intent & Why

The daily scraper (`scraper.py`) only sees the Best of SNO RSS feed, which
exposes the **10 most recent** winning stories and nothing older. For QDoRA
fine-tuning (Layer 3) a 10-story corpus is far too small. This feature does
a **one-time historical backfill** of every Best of SNO winning story
published since **2026-01-01**, so the advisor starts life with a real
corpus (~1,600 stories) instead of waiting ~5 months for daily accumulation
to reach the same size.

Every post on bestofsno.com *is* a winning story — the site is the Best of
SNO archive — so enumerating posts in the date window **is** the winner set.
No winner/non-winner filtering is needed here (that distinction belongs to
Layer 2's school-site scrape).

## 2. Goals

- Collect all Best of SNO winners **published 2026-01-01 → today** into a
  new `best_of_sno/data/archive.csv` with the **same 12 columns** as the
  daily scraper's `new.csv`/`old.csv` (schema parity so Layers 2–4 read all
  three files as one corpus).
- Stay strictly within `robots.txt`: only clean (no-`?`) URLs, honor
  `Crawl-delay: 6`, send the existing research User-Agent.
- Be **resumable**: a 2.7-hour run must survive an interrupt and continue
  where it left off without re-fetching or duplicating.
- **Dedup-align** with the daily scraper: a story that is both in the
  archive and later seen by the daily feed must never appear twice.
- Reuse the daily scraper's parsing core; add only what is genuinely new.

## 3. Non-Goals

- Not changing the daily scraper's **rotation** or `new.csv`/`old.csv`/
  `state.json` *flow*. Backfill writes its own file and its own checkpoint.
  (One narrow, safe touch to `scraper.load_state` is in scope — see §8
  "Overlap" — adding `archive.csv` to the seen-id union so the daily run
  never re-writes a backfilled winner. This changes dedup inputs, not
  rotation behavior.)
- Not backfilling before 2026-01-01 (the ~5,600 older posts are ignored).
- Not Layer 2 (other schools' sites) — separate feature.
- Not a daily/repeating job — this runs once (re-runnable, but idempotent).

## 4. Anti-Goals (would make this a failure even if it "works")

- **Silently wrong authors.** The WordPress REST `author` field is `1`
  (site admin) and the `staff_name` taxonomy 404s over REST, so a REST-based
  author would fill every row with garbage. The byline MUST come from the
  rendered page's `.sno-story-byline`.
- **A politeness violation.** Any request to a `?`-bearing URL, or a burst
  faster than one request / 6s, fails the spec regardless of data quality.
- **A run that can't resume.** Losing 2 hours of progress to one dropped
  connection is a failure.
- **Schema drift.** A 13th column, a renamed column, or a different `id`
  scheme than the daily feed breaks the "one corpus" promise.

## 5. Constraints (verified 2026-10-29 against the live site)

- `robots.txt`: `Disallow: /cgi-bin/`, `/?s=`, `/*?*`; `Crawl-delay: 6`.
  → No query strings anywhere. Sitemaps and post URLs are clean paths.
- Sitemap index: `https://bestofsno.com/wp-sitemap.xml` →
  `wp-sitemap-posts-post-{1..4}.xml`. Each `<url>` has `<loc>` + `<lastmod>`.
- In-window counts: post-3 has 353 URLs with `lastmod ≥ 2026-01-01`,
  post-4 has all 1,266. ~**1,619** candidates. At 6s each ≈ **2.7 hours**.
- Post URL shape: `https://bestofsno.com/<numeric-id>/<category>/<slug>/`.
- Post page carries `.sno-story-byline` =
  `"By <Author>, <School> • <Month DD, YYYY>"` — byline + published date.
- `id` scheme: daily feed uses guid `https://bestofsno.com/?p=<numeric-id>`.
  Backfill constructs the identical string from the URL's numeric id, so
  dedup aligns across backfill and daily.
- Python 3.14; deps already present: `requests`, `beautifulsoup4`
  (`feedparser` not needed here).

## 6. How It Works (the decided design)

New module `best_of_sno/backfill.py`. Fetching is new; parsing reuses
`scraper.py`.

**6.1 Enumerate (robots-safe, cheap).**
Fetch the 4 post sub-sitemaps. Parse `(<loc>, <lastmod>)` pairs. Keep locs
with `lastmod ≥ 2026-01-01`. This is the candidate list (~1,619). Sitemaps
cost 4 requests total and carry no `?`.

**6.2 Resume.**
Checkpoint file `best_of_sno/data/backfill_state.json`:
`{"done_ids": [...], "window_start": "2026-01-01"}`. On start, load it; skip
any candidate whose id is already in `done_ids`. `archive.csv` is written
**append-wise** (header once), and each successfully written row's id is
added to `done_ids`, with the checkpoint saved every N rows (e.g. 25) and at
exit. A re-run with no new candidates is a no-op.

**6.3 Fetch + parse each post (one HTML request each, 6s apart).**
For each candidate URL:
- `fetch` the HTML (reuse the retry/UA/timeout pattern from
  `scraper.fetch_feed`, generalized to return page bytes).
- Parse with BeautifulSoup:
  - `.sno-story-byline` text → split on `•` into byline + date string.
    - byline → `scraper.parse_byline(byline)` → `(author, school)`.
    - date string (`"October 28, 2026"`) → ISO `published`.
  - title ← `<h1>` / `og:title`.
  - body HTML ← the SNO article content container → `scraper.strip_html`,
    `scraper.word_count`, `scraper.extract_source_site`.
  - categories ← the rendered category link(s) on the page, `;`-joined to
    match the daily feed's multi-category format (fall back to the URL's
    single category segment if no links found); unescape HTML entities.
  - `id` ← `https://bestofsno.com/?p=<numeric-id from URL>`.
  - `url` ← the post URL; `scraped_at` ← now (ISO).
- **Published-date gate:** if parsed `published < 2026-01-01`, skip the row
  (a pre-2026 post edited in 2026 slipped past the `lastmod` prefilter) but
  still mark its id done.
- Build the record keyed by `scraper.COLUMNS`; append via a CSV writer that
  applies `scraper._csv_safe` (formula-injection guard) and
  `csv.QUOTE_ALL`, exactly as the daily scraper does.
- Sleep 6s between requests (skip the sleep after the last one).

**6.4 CLI.** `python -m best_of_sno.backfill` with:
`--data-dir` (default `best_of_sno`), `--since` (default `2026-01-01`),
`--limit N` (cap candidates — for a small trial run), `--dry-run` (enumerate
+ report counts, fetch nothing), `--delay` (default 6.0; override only for
tests). Logs to `logs/backfill.log` + console, reporting progress
(`fetched 120/1619 …`) so a long run is observable.

## 7. Output

`best_of_sno/data/archive.csv` — same 12 columns as `new.csv`:
`id,url,title,published,categories,author,school,summary,body,word_count,source_site,scraped_at`.
`.gitignored` like the other runtime data. One row per in-window winner.

## 8. Edge Cases & Decisions

- **`lastmod` ≠ published:** handled by the §6.3 published-date gate.
- **Missing/odd byline:** `.sno-story-byline` absent → log a warning, write
  the row with empty author/school rather than dropping the story (body is
  the fine-tuning signal; byline is metadata). Multi-author bylines already
  handled by `parse_byline` (empty school).
- **`•` separator variants:** split on the bullet; if absent, treat the
  whole block as byline and leave `published` to a fallback (page `<time>` /
  og:article:published_time) — confirmed present in Task 1.
- **Overlap with daily feed:** the ~10 most-recent winners are in both
  `archive.csv` and `new.csv`. Because both use the identical `?p=<id>` id,
  we close this at the write side: `scraper.load_state` gains `archive.csv`
  as a third input to its seen-id union (it already unions `new.csv` +
  `old.csv`), so once the backfill has run, the daily scraper treats those
  ids as seen and never re-writes them into `new.csv`. Result: each winner
  lives in exactly one of the three files. This is the only edit to
  `scraper.py` and touches dedup inputs only, not rotation.
- **Interrupted run:** checkpoint + append-write (§6.2).
- **Category names with entities** (`Arts &amp; Entertainment`): unescape.
- **Not winners?** N/A — entire site is winners.

## 9. Left to the Builder

- Exact BeautifulSoup selectors for title/body/category containers and the
  date fallback — **Task 1 of the plan verifies these against 3 saved real
  pages** before the parser is written (test-first, offline fixtures).
- Checkpoint-save cadence (N rows) — any value in ~10–50 is fine.
- Log format specifics.
- Whether to factor the shared fetch-with-retry into a helper imported by
  both modules, or copy the small pattern — builder's call.

## 10. Open Risk (flagged, mitigated)

The parser depends on SNO's page markup being consistent across ~1,619
posts. Mitigation: Task 1 pins selectors against several real pages saved as
fixtures; the published-date gate and the warn-don't-drop byline rule keep a
markup surprise from silently corrupting or losing data. A trial
`--limit 20` run before the full 2.7h pass is recommended in the plan.
