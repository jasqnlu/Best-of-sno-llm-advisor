# Best of SNO — School-Site Non-Winner Collection (Layer 2) Design

**Status:** Draft for approval
**Date:** 2026-10-29
**Parent design:** `docs/superpowers/specs/2026-10-28-best-of-sno-advisor-design.md` (§5, Layer 2)
**Builds on:** `best_of_sno/backfill.py` (historical backfill, shipped) and
`best_of_sno/scraper.py` (daily scraper, shipped)

## 1. Intent & Why

Layer 1 gave us every Best of SNO **winner** published since 2026-01-01
(`archive.csv`, ~1,622 stories). A winners-only corpus can describe what
good looks like, but it cannot train a model to answer the question this
project exists to answer — *"how likely is this article to win?"* — because
a classifier needs a **negative class**: real high-school journalism that
did **not** win.

Layer 2 collects that negative class. It scrapes five high-school news
sites, and for each article asks one question: *is this article in the
winners corpus?* If yes → `winner`; if no → `non_winner`; if the match is
ambiguous → `uncertain` (held out for a human to rule on). The winners
corpus is the **answer key**; the school sites supply the articles to be
judged.

**The winners corpus is all three winner files, not just `archive.csv`.**
By design (`backfill.run_backfill`), a winner the daily scraper already
captured into `new.csv`/`old.csv` is *excluded* from `archive.csv`, so each
winner lives in exactly one of the three files. Matching only `archive.csv`
would therefore mislabel any in-window winner the daily run happened to
catch as a `non_winner` — the §4 poisoned-negative anti-goal. So the
labeler loads winners from **`archive.csv` ∪ `new.csv` ∪ `old.csv`**,
mirroring `scraper.load_state`'s existing seen-id union. (Verified
2026-10-29: `new.csv` currently holds 0 in-window winners for the five
schools and `old.csv` does not yet exist, so the union is harmless today —
but it is the robust choice once the daily scraper has run.)

This directly unblocks the chance-score model (Layer 4), which is the
centerpiece of the tool. (During brainstorming we decided the fine-tuned
*advice* model is likely a weaker duplicate of calling Claude directly, so
the plan now leads with the empirical chance score; advice becomes Claude
grounded on that score plus retrieved winners. See §3 Non-Goals.)

## 2. Goals

- Enumerate and fetch every article on the five sites **published
  2026-01-01 → 2026-10-10** (customizable), reusing Layer 1's sitemap
  enumeration, post parser, politeness, and resumable writer.
- **Label each article** by exact normalized-title match against that
  school's winners in `archive.csv`: `winner` / `non_winner` / `uncertain`.
- Write confident rows to `best_of_sno/data/layer2.csv` in the **same 12
  columns as the archive**, plus `label`, `matched_id`, `source_site`.
- Write every ambiguous case to `best_of_sno/data/uncertain.csv` with both
  the school title and the candidate archive winner side by side, so a
  human can resolve it. Uncertain rows are **not** training data until
  resolved.
- Stay strictly within each site's `robots.txt` (verified identical to
  bestofsno.com: no `?`-URLs, `Crawl-delay: 6`, research User-Agent).
- Be resumable across a ~6–7-hour multi-site run.

## 3. Non-Goals

- **Not** scraping the badge/logo. Verified 2026-10-29: a confirmed winner
  ("The art of preservation: Fanmaking", Carlmont, published 2026-01-05)
  has **no** "Best of SNO" text, no bestofsno.com link, and no award image
  anywhere in its served HTML. The badge is JS-injected or exists only on
  bestofsno.com. The archive cross-reference replaces it and is exact.
- **Not** building the chance-score model (Layer 4) — Layer 2 only produces
  its training data.
- **Not** building a fine-tuned advice model. Decided during brainstorming:
  distilling Claude's critiques yields a weaker copy of Claude. Advice will
  be Claude at inference time, grounded on the Layer 4 score and retrieved
  archive winners. (Recorded here so a future reader knows it was a
  deliberate cut, not an omission.)
- **Not** re-collecting winners from bestofsno.com — we already have them.
  But see §6.4: we **do** store the *school-site* copy of matched winners.
- **Not** modifying `scraper.py` or `backfill.py` *behavior*. Layer 2
  imports their helpers. A **behavior-preserving** refactor to let a helper
  serve both modules **is** in scope, and two are required (see §6.5):
  (a) give `backfill.post_id_from_url` an optional `host` parameter
  defaulting to `"bestofsno.com"` (and thread it through `parse_post` as an
  optional arg, default unchanged), so the backfill's output is byte-for-byte
  identical while Layer 2 can pass each school's host; (b) Layer 2 writes
  through its **own** wider-column writer rather than `backfill.append_rows`,
  because that writer is bound to the archive's 12 `COLUMNS` with
  `extrasaction="ignore"` and would silently drop `label`/`matched_id`/
  `source_site`. Neither change alters what the shipped modules do when
  called as they are today; the plan's final review must confirm the
  backfill's own tests still pass unchanged.

## 4. Anti-Goals (would make this a failure even if it "works")

- **A poisoned negative class.** A true winner mislabeled `non_winner`
  because its title was reworded between the school site and the SNO
  republish teaches the chance model that a winner is a loser. The
  `uncertain` bucket exists precisely to catch near-misses before they
  poison training; a silent mislabel is the worst outcome here.
- **Distribution leakage.** If winner rows carried bestofsno.com body text
  while non-winner rows carried school-site body text, the classifier could
  learn *which site rendered the page* instead of *article quality*. All
  rows — winners included — must carry the **school-site** body (§6.4).
- **Window skew.** Non-winners drawn from a different date range than the
  winners lets the model learn *when* a story was published instead of *how
  good* it is. Both windows share the 2026-01-01 floor.
- **A politeness violation.** Any `?`-bearing URL, or faster than one
  request / 6s per host, fails the spec regardless of data quality.
- **Schema drift.** The 12 archive columns must stay identical so Layers
  3–4 read `archive.csv` and `layer2.csv` as one corpus; Layer 2's extra
  columns (`label`, `matched_id`, `source_site`) are appended, never
  substituted.

## 5. Constraints (verified 2026-10-29 against the live sites)

- Five sites, all on the SNO `snoflex` WordPress platform, all with the
  identical sitemap + robots structure Layer 1 already handles:
  `scotscoop.com`, `elestoque.org`, `harkeraquila.com`,
  `torreypinesfalconer.com`, `theburlingameb.org`.
- `robots.txt` on each: `Disallow: /cgi-bin/`, `/?s=`, `/*?*`;
  `Crawl-delay: 6`. Same rules as bestofsno.com.
- Sitemap index `https://<host>/wp-sitemap.xml` →
  `wp-sitemap-posts-post-{1..N}.xml` (N varies per site, e.g. Scotscoop 7).
  Each `<url>` carries `<loc>` + `<lastmod>`. Other sub-sitemaps
  (`page`, `staff_profile`, `flipbook`, `infobox`, …) are **skipped** — we
  take only `posts-post-*`, exactly as the backfill does.
- Post pages carry the same markup Layer 1 parses: `og:title`,
  `.sno-story-byline` (`"By <Author>, <School> • <Month DD, YYYY>"`),
  `article:section`, `.sno-story-body-content`.
- Scale (measured on Scotscoop, the largest): ~818 in-window articles.
  Five sites ≈ **~4,000 articles**. At 6s each ≈ **~6.7 hours** of fetching.
- Archive winners by school (the positive-match ceiling):
  Carlmont 61, Monta Vista 14, Torrey Pines 9, Burlingame 9, Harker 7 —
  **~100 total** (before the Oct 10 cutoff trims a few). See §10 Open Risk.
- Python 3.14; deps already present (`requests`, `beautifulsoup4`,
  `defusedxml`). No new dependency.

## 6. How It Works (the decided design)

New module `best_of_sno/layer2.py`. Enumeration, fetching, and post parsing
are **imported from `backfill.py`**; what is genuinely new is per-site
configuration, the title-match labeler, and the three-bucket writer.

**6.1 Per-site configuration + winner-corpus load.**
On start, load the winners corpus once: read rows from `archive.csv`,
`new.csv`, and `old.csv` (any that exist), and index them by school name.
A small table maps each host to its school name (verified present in the
corpus):

| host | school name in archive | archive winners |
|------|------------------------|-----------------|
| scotscoop.com | Carlmont High School | 61 |
| elestoque.org | Monta Vista High School | 14 |
| torreypinesfalconer.com | Torrey Pines High School | 9 |
| theburlingameb.org | Burlingame High School | 9 |
| harkeraquila.com | The Harker School | 7 |

**6.2 Enumerate (robots-safe, cheap).**
For each host, fetch its `posts-post-*` sub-sitemaps (reusing
`backfill.fetch_all_post_sitemaps`, generalized to take a base host), parse
`(<loc>, <lastmod>)`, keep `lastmod ≥ 2026-01-01`. 6s between sitemap
fetches, as now.

**6.3 Fetch + parse each post (one HTML request each, 6s apart per host).**
Reuse `backfill.fetch_page` + `backfill.parse_post` (the latter now taking
the host arg from §3, so the row's `id` is `https://<host>/?p=<n>`).
`parse_post` already: returns the 12-column record, gates on published date
(`< since` → drop), pulls title/byline/category/body, and reuses the
scraper's strip/word-count helpers. Layer 2 adds two gates:
- an **upper** date gate: drop (but mark done) any article whose parsed
  `published > --until` (default `2026-10-10`), because its win status may
  not be settled yet.
- an **undated** gate: `parse_post` returns `published=""` when the byline
  is missing/unparseable, and neither date gate fires on an empty string.
  Such an article cannot be confirmed in-window, so keeping it as a
  `non_winner` risks the §4 window-skew anti-goal. Route every undated
  in-window article to `uncertain.csv` with `reason="undated"` (§6.5) —
  surfaced for the same manual review as a title near-miss, never silently
  dropped into the negative class and never silently discarded.

**6.4 Label each in-window article (the new logic).**
`classify(record, winners_for_school) -> (label, matched_id)` where
`winners_for_school` is the **corpus** rows (archive ∪ new ∪ old, §6.1)
whose `school` equals this host's mapped name:
- Normalize both titles: lowercase, strip punctuation, collapse whitespace.
- **Exact normalized match** to a winner title → `("winner", <archive id>)`.
- **No match, and no near-match** → `("non_winner", "")`.
- **Near-match** (either: normalized-title similarity above a threshold the
  builder picks in ~0.85–0.95, **or** author + publish-date equal an
  archive winner while the title differs) → `("uncertain", <candidate id>)`.

Every row — **including winners** — keeps the **school-site** body from
§6.3 (the anti-goal in §4). The archive supplies only the label and the
`matched_id`, never the text.

**6.5 Three-bucket write (resumable).**
- `winner` / `non_winner` → `layer2.csv` (12 archive cols + `label` +
  `matched_id` + `source_site=<host>`), appended via **Layer 2's own**
  atomic writer (read-existing + tmp + `os.replace`, the backfill's
  pattern), bound to Layer 2's full column list — **not**
  `backfill.append_rows`, which is hardwired to the 12 `COLUMNS` and would
  drop the extra three (§3). It applies the same `scraper._csv_safe`
  formula-injection guard. Quoting is `QUOTE_MINIMAL` to **match the shipped
  `archive.csv`** (the design previously said `QUOTE_ALL`; corrected after
  verifying the shipped writer uses `QUOTE_MINIMAL`), so all corpus files
  share one dialect.
- `uncertain` → `uncertain.csv`, same columns plus `reason`
  (`"title-nearmatch"` or `"undated"`), `candidate_title`, and
  `candidate_url` (the corpus winner it nearly matched, empty for
  `undated`), for human review.
- Checkpoint `layer2_state.json` (`done_ids`), unioned on load with the ids
  already in `layer2.csv` **and** `uncertain.csv`, so a resumed or re-run
  pass never re-fetches or double-writes. `id` =
  `backfill.post_id_from_url(url, host=<host>)` → `https://<host>/?p=<n>` —
  per-host, so ids never collide across sites. (This is why the §3 host
  parameter is required: reused as-is, `post_id_from_url` hardcodes
  `bestofsno.com` and every Layer 2 id would collide.) Fetch failure skips
  without marking done (retries next run), exactly as the backfill does.

**6.6 CLI.** `python -m best_of_sno.layer2` with:
`--data-dir` (default `best_of_sno`), `--since` (default `2026-01-01`),
`--until` (default `2026-10-10`), `--sites` (default all five; a subset for
trial runs), `--limit N` (cap candidates per site), `--dry-run` (enumerate +
report counts, fetch nothing), `--delay` (default 6.0; tests override). Logs
to `logs/layer2.log` + console, reporting per-site progress
(`scotscoop.com: fetched 120/818 (winner=8 non=110 uncertain=2)`).

## 7. Output

- `best_of_sno/data/layer2.csv` — confident rows. Columns:
  `id,url,title,published,categories,author,school,summary,body,word_count,source_site,scraped_at,label,matched_id`.
  (`source_site` here is finally populated — the host domain — unlike the
  archive where it was unavailable.)
- `best_of_sno/data/uncertain.csv` — ambiguous rows for manual review, same
  columns plus `reason` (`title-nearmatch` | `undated`), `candidate_title`,
  `candidate_url`.
- `best_of_sno/data/layer2_state.json` — resume checkpoint. `.gitignored`
  like all runtime data.

## 8. Edge Cases & Decisions

- **Title reworded between school site and SNO republish:** caught by the
  `uncertain` bucket's author+date corroboration; surfaced, never silently
  mislabeled.
- **Same title, two different articles** (e.g. a recurring column): author +
  publish-date disambiguate; if still ambiguous → `uncertain`.
- **Multi-author bylines:** `parse_byline` already yields empty school; the
  label uses the *host→school* map, not the byline school, so this does not
  affect labeling.
- **Article published after `--until`:** dropped, id marked done (its win
  status isn't settled; including it would create a fake negative).
- **Winner published in-window but its SNO republish fell outside the
  archive window:** impossible for this window — the republish carries the
  original publish date, and the archive is complete for 2026-01-01 → today.
- **A site adds/removes a `posts-post-*` file mid-run:** enumeration is
  re-run each pass; the checkpoint makes re-enumeration idempotent.
- **Non-ASCII / smart-quoted titles:** normalization unescapes HTML entities
  and strips punctuation before comparison, so "don't" vs "don't" match.

## 9. Left to the Builder

- The exact normalized-title similarity metric and threshold (~0.85–0.95):
  pin it in the plan's Task that writes `classify`, against saved real
  fixtures (reuse the backfill fixture style — offline HTML + a tiny
  archive fixture).
- Whether to factor Layer 1's `fetch_all_post_sitemaps`/`fetch_page` into a
  shared helper both modules import, or pass a host parameter — builder's
  call, as long as `backfill.py` behavior is unchanged.
- Checkpoint-save cadence (~25 rows, matching the backfill).
- Log line format specifics.

## 10. Open Risk (flagged, mitigated)

- **Small positive class.** Only ~100 of the ~4,000 collected articles are
  winners (and they cluster: 61 are Carlmont). A classifier with ~100
  positives against ~3,700 negatives is thin and imbalanced. This is a
  **Layer 4 modeling problem, not a Layer 2 collection problem** — Layer 2's
  job is to collect honestly. Mitigations available to Layer 4, noted here
  so they are not forgotten: (a) augment positives with the full ~1,622
  archive winners despite the source-distribution caveat, weighing that
  against the §4 leakage risk; (b) use class weighting / calibration; (c)
  add more SNO sites to Layer 2 later (the engine is site-agnostic). The
  design deliberately does **not** fabricate positives to balance classes.
- **Title-normalization false matches** across different articles sharing a
  title: mitigated by author+date corroboration and the `uncertain` bucket;
  a wrong exact-match would need identical normalized title *and* the
  builder's metric to treat it as exact — low, and the review file catches
  the near cases.
- **Parser drift across five sites:** all five share the `snoflex` theme and
  the markup Layer 1 already parses, but the plan's first Task saves one
  real post from **each** site as a fixture and asserts the parser handles
  all five before the crawl runs.

## 11. Amendments from live data (2026-10-30)

Building and trial-running Layer 2 against the live sites showed several
§5/§8 premises to be false. The code follows these amendments; where they
conflict with earlier sections, this section wins.

- **The five sites are not uniform** (contradicts §5). Scot Scoop uses slug
  permalinks and El Estoque WordPress date permalinks (`/2026/01/13/...`), so
  there is no post number in the URL. `?p=<1st segment>` would give every
  2026 El Estoque article the id `?p=2026`. Ids are `https://<host>/?p=<n>`
  for numeric permalinks, otherwise the canonical URL (`layer2.post_id`).
  Harker serves Yoast sitemaps (`post-sitemapN.xml`), puts the date in
  `.sno-story-date`, and suffixes `og:title` with " - Harker Aquila".
  Bylines on the school sites read "Name , Staff Role", not "By Name , School".
  Author-less bylines hold only a `.time-wrapper` date.
- **Best of SNO republishes 3–40 days after the school** (median 18,
  measured on 17 Carlmont winners). This contradicts §8, which assumed the
  republish keeps the original date. So:
  - Dates "corroborate" when the corpus date is −1..60 days *after* the
    school date, never when they are equal.
  - A lone exact-title match must fit that lag window to be a `winner`.
    Otherwise it is `uncertain` / `title-ambiguous` (e.g. another
    installment of a recurring column).
- **Window is 2025-12-01 → 2026-09-15** (replaces §2's 2026-01-01 →
  2026-10-10). The start date: 4 of 9 January-dated Carlmont winners were
  published on Scot Scoop in December. The end date: the run date minus the
  40-day maximum lag, so every included article has had time to win. The
  winners corpus must start no later than the crawl window. Otherwise
  winners from the gap are labeled `non_winner`, so the corpus was
  backfilled from 2025-12-01, and Layer 2 refuses a `--since` earlier
  than the corpus start (with 7 days' slack).
- **`uncertain.csv` reasons** are `undated`, `title-nearmatch`,
  `author-date` and `title-ambiguous` (widens §7's two).
