# Best of SNO Advisor — Design

*Date: 2026-10-28*
*Author: Jason Lu (online editor) + Claude*

## 1. Intent and the why

A newsroom tool for a high-school/college publication that hasn't been
winning many **Best of SNO** honors. Best of SNO (`bestofsno.com`) is a
daily showcase of the strongest stories across the SNO Sites network —
getting a story picked is a mark of quality.

The tool helps the publication's journalists write Best-of-SNO-caliber
work by doing two things against any draft:

1. **Advice** — concrete, implementable suggestions ("the lede buries the
   human stakes; lead with the sticky-note detail").
2. **A chance bar** — a single Best-of-SNO-likeness score (0–100%) shown
   next to the advice, so a writer sees both the number and the specific
   fixes that would move it.

The **why**: the editor can see what winning stories have in common but
can't manually coach every draft toward that bar. This tool scales that
coaching, and makes "what makes a story Best-of-SNO-worthy" concrete and
measurable instead of a gut feeling.

## 2. Goals, non-goals, anti-goals

**Goals**
- Keep a growing, de-duplicated archive of Best of SNO **winning** stories
  (full text + metadata) that grows automatically every day.
- Eventually: an advice model and a calibrated-ish chance bar a journalist
  can run a draft through.
- Keep the chance bar **interpretable** — the number is built from named,
  explainable sub-scores that double as the advice.

**Non-goals**
- Not a public product. Internal newsroom use.
- Not republishing other students' stories. We store full text for private
  analysis only and link to originals.
- Not a real-time service. A daily batch job is fine.

**Anti-goals (would make this a failure even if it "works")**
- A chance bar that outputs confident numbers with nothing real behind them
  (an LLM guessing a percentage). If the number isn't grounded in labeled
  winners-vs-non-winners data, it's worse than no number.
- Advice that's generic writing-tips boilerplate rather than specific to the
  draft in front of it.
- Scraping that ignores the site's wishes (robots.txt / crawl-delay) and
  gets us blocked or is disrespectful to other students' work.

## 3. The architecture (the layers)

Built in layers; only Layer 1 is built now.

**Layer 1 — Daily scraper (THIS PHASE).** A Python job, run once a day,
pulls newly published Best of SNO stories from the RSS feed and maintains a
de-duplicated archive on disk (`new` = today's batch, `old` = everything
earlier). These are the **positive / "this won"** examples. Full spec in
§5.

**Layer 2 — School-site corpus + auto-labeling (later).** Two sources of
the **negative / "this didn't win"** class:

- **Our own publication's articles** (editor has full access).
- **Other SNO-network high-school journalism sites**, scraped broadly, to
  scale up and diversify the negatives.

The key move is **auto-labeling by cross-reference against the Layer-1
archive** instead of hand-labeling: a scraped school-site story that *also
appears in the Best of SNO archive* is a **winner (1)**; one that doesn't is
a **non-winner (0)**. This makes Layer 1 the labeling lookup table.

*Matching mechanism (verified feasible 2026-10-28):* Best of SNO re-hosts
article text but references the school's images at
`<school-domain>/wp-content/uploads/...`, and its story pages carry a
permalink (`/?p=NNNN`) to the original post. So a Best of SNO entry can be
tied back to its originating school site by **source domain + title/author**,
or by **exact source permalink** (needs a per-story page fetch). Layer 1 will
capture `source_site` from feed image hosts now (free) to seed this.

*Caveats baked in:*
- **"Didn't win" is a very noisy, very imbalanced label.** Best of SNO
  selects a tiny fraction of the whole network's daily output, so most
  non-winners are perfectly good stories that simply weren't picked. Expect
  heavy class imbalance (plausibly hundreds of non-winners per winner). The
  chance bar must be trained/calibrated for this (subsample or reweight
  negatives, calibrate probabilities) or it will just learn to always say
  "low." The bar therefore reads as "how Best-of-SNO-like" — not a verdict.
- **Each school site has its own robots.txt and crawl rules** — honor each;
  this is a much larger crawl surface than the single daily feed.
- **Site selection (DECIDED, seed list)** — our own site plus:
  `theburlingameb.org` (The Burlingame B), `scotscoop.com` (Scot Scoop,
  Carlmont), `elestoque.org` (El Estoque, Monta Vista), `harkeraquila.com`
  (Harker Aquila), and `torreypinesfalconer.com` (The Falconer — a confirmed
  Best of SNO winner in the 2026-10-28 feed). More programs to be added
  **data-driven**: once Layer 1 has accumulated `source_site` values, the
  most frequent domains in the winners archive reveal which programs win most
  and should join the crawl list.
- **Date window (DECIDED)** — collect each site's articles **published
  2026-01-01 through 2026-10-15** only: a fixed, reproducible historical
  corpus that does not overlap the live daily feed starting late Oct 2026.
  (Interpretation of "from 2026 up to October 15"; confirm if a different
  start was meant.)

**Layer 3 — Advice model (later).** An LLM fine-tuned with **QDoRA** on
Google Colab. Trained not on raw article text (that only teaches *imitation*
of winning style) but on **instruction-shaped pairs** (`weaker draft →
specific advice`, constructed from winners vs. non-winners). It reads any
story and outputs (a) prose advice and (b) a set of **named sub-scores**
(e.g. lede strength, sourcing depth, structure, originality/enterprise,
timeliness, writing craft — exact rubric decided in Layer 3 design).

**Layer 4 — Chance bar (later).** A small **logistic regression** takes the
Layer-3 sub-scores as *features* and outputs a probability (0–100%). Fit on
the Layer-1 winners + Layer-2 non-winners. Logistic (not plain linear) so
the output stays within 0–1.

Why this shape: it pushes the "needs tons of data" burden onto the LLM
(which already knows English), leaving a model with only ~7 weights to fit —
feasible on the few dozen-to-few-hundred labeled articles a single
publication realistically has. And because the probability is built from
named sub-scores, the chance bar *is* the advice: "lede 3/10 is what's
dragging you down."

```
Best of SNO feed ──(Layer 1 scraper)──▶ winners archive (CSV)
                                               │
our site + other school sites ─(Layer 2 scrape)─┐
          auto-labeled winner/non-winner by ◀──┘ (cross-ref archive)
                                               ▼
                         (Layer 3) QDoRA advice LLM ──▶ prose advice
                                               │ + named sub-scores
                                               ▼
                         (Layer 4) logistic regression ──▶ chance bar %
```

## 4. Constraints

- **robots.txt (verified 2026-10-28).** `bestofsno.com/robots.txt` has
  `Disallow: /*?*` — **any URL containing a query string `?` is
  disallowed**, and `Crawl-delay: 6`. Consequences:
  - The `/feed/` path is allowed (no query string). ✅
  - The spec's suggested `?paged=2` feed pagination is **disallowed** —
    do not use it.
  - Query-string backfill is out; path-based `/category/<name>/page/N/`
    pages are allowed and are the fallback for filling gaps.
  - Honor a **6-second** crawl-delay for any multi-request fetching.
- **The REST API** (`/wp-json/wp/v2/posts`) is avoided — it needs query
  params to be useful, which robots disallows, and a prior fetch was blocked.
- **Copyright/etiquette.** Store full text privately; never republish; link
  to original URLs; descriptive User-Agent with contact email.
- **Platform.** macOS laptop (Python 3.14). CSV storage. Scheduling via cron
  or launchd. Colab reserved for Layer 3.

## 5. Layer 1 — Daily scraper (full spec for the builder)

This is the only layer being built now. It follows the original design spec
(`best-of-sno-daily-scraper.md`), amended by the verified findings above.

### 5.1 Data source
- **Primary: the RSS feed** `https://bestofsno.com/feed/`. Verified
  2026-10-28: returns HTTP 200, holds ~10 items, and includes full
  `<content:encoded>` body plus a `By Author, School` byline in
  `<dc:creator>`. So for the common case we **never fetch a story page** —
  the feed alone fills every column, keeping us on the allowed path.
- **Gap-fill fallback (optional, rarely needed):** path-based category pages
  `/category/<name>/page/N/` parsed with BeautifulSoup, at 6s/request. Used
  only if runs are missed and the feed has rotated items out.

### 5.2 Files on disk
```
best_of_sno/
├── scraper.py
├── data/
│   ├── new.csv          # stories found on the most recent run
│   ├── old.csv          # all earlier stories (archive)
│   └── state.json       # last_run + seen_ids
└── logs/
    └── scraper.log
```

### 5.3 Columns (both CSVs)
`id` (feed `<guid>`, stable), `url` (`<link>`), `title`, `published`
(`<pubDate>` → ISO 8601), `categories` (all `<category>`, `;`-joined — these
are the SNO *section* labels: Sports, Features, Opinions, …), `author` +
`school` (parsed from `<dc:creator>`; see 5.6), `summary` (`<description>`,
HTML stripped), `body` (`<content:encoded>`, HTML stripped), `word_count`
(from `body`), `source_site` (originating school domain, parsed from the
hosts of `<img>` URLs in `<content:encoded>` — e.g. `torreypinesfalconer.com`;
empty if none found; seeds Layer-2 cross-referencing at zero extra request
cost), `scraped_at` (run time).

### 5.4 state.json
```json
{ "last_run": "2026-10-28T08:00:00-07:00",
  "seen_ids": ["https://bestofsno.com/?p=89927", "..."] }
```
`seen_ids` is the source of truth for "already stored". Rebuilt from
`old.csv` + `new.csv` if the file goes missing.

### 5.5 Daily run logic
1. Load `state.json` (or rebuild `seen_ids` from the CSVs).
2. Fetch the feed (polite User-Agent, timeout, retries).
3. Parse items → story records.
4. Keep only records whose `id` is NOT in `seen_ids` → `fresh_batch`.
5. **Rotate:** append all of `new.csv` onto `old.csv`, then clear `new.csv`
   (header only).
6. Write `fresh_batch` into `new.csv`.
7. Add `fresh_batch` ids to `seen_ids`; set `last_run = now`.
8. Save `state.json`. Log counts: `moved_to_old`, `new_found`.

### 5.6 Rules, edge cases, and decisions

- **Rotation policy — DECIDED: rotate every run**, even with zero new
  stories (an empty-day `new.csv` is acceptable and honest). `--no-rotate`
  skips it for testing. *(This is the first of the two options the original
  spec left open; noted as our call.)*
- **School parsing — DECIDED: best-effort heuristic, never blocks a row.**
  `<dc:creator>` looks like `By {names}, {School}`. Strip leading `By `; if a
  trailing comma-segment doesn't look like part of an "A, B, and C" author
  list, treat it as `school`, else leave `school` empty. Imperfect by design;
  the story page is the only reliable source and we don't fetch it by
  default.
- **Duplicates:** always check `seen_ids` first; never trust absence from a
  CSV.
- **Edited stories:** ignored (same id). Optional later: content-hash compare.
- **Crash safety:** write `*.tmp` then rename over the real files; update
  `state.json` **last**, so a crash never marks a story seen without saving
  it.
- **First run:** `old.csv` empty, everything goes to `new.csv`. Optional
  one-time backfill via the path-based category fallback at 6s/request.
- **Missed days:** `new` holds everything since `last_run`; gaps beyond the
  feed's ~10-item window need the category fallback.

### 5.7 Functions / CLI
```
fetch_feed(url) -> raw feed
parse_items(feed) -> list[dict]
enrich(record) -> dict         # optional story-page fetch; off by default
load_state(path) -> dict
save_state(path, state)
rotate(new_path, old_path)
write_new(new_path, records)
main()                         # wires steps 1–8
```
Flags: `--dry-run` (print, touch nothing), `--no-rotate` (testing).

### 5.8 Libraries
`requests`, `feedparser`, `beautifulsoup4`, `pandas` (CSV via pandas or the
stdlib `csv` module — builder's call).

### 5.9 Scheduling
cron at 08:00 daily, or launchd `StartCalendarInterval` if missed-wake runs
matter. GitHub Actions is a later option if an always-on box is wanted.

### 5.10 Testing checklist
- First run: `new.csv` filled, `old.csv` empty, `state.json` created.
- Second run same day: previous `new` rows moved to `old`, no duplicates.
- Delete `state.json` → rebuilds from CSVs, re-adds nothing.
- Kill mid-run → no lost/duplicated rows next run (tmp+rename proves out).
- `--dry-run` changes nothing on disk.

## 6. What's left to the builder (Layer 1)

- CSV via `pandas` vs stdlib `csv` (either fine; stdlib keeps deps lighter).
- Exact retry/backoff numbers and timeout values.
- Log format and verbosity.
- Whether to implement the category-page backfill now or stub it for later
  (the daily path works without it).

## 7. Later phases (not being designed in detail yet)

- **Layer 2** needs its own short design: which school sites to crawl (ours
  + a few strong programs first), per-site robots handling, the SNO/FLEX
  page selectors, and the exact cross-reference matching rule (source domain
  + title/author vs. exact permalink) and how to handle the heavy class
  imbalance it will produce.
- **Layer 3** needs a rubric decision (which sub-scores), the instruction-
  pair construction method, and QDoRA/Colab specifics.
- **Layer 4** is a few lines of scikit-learn once Layers 1–3 produce features
  and labels — but its trustworthiness depends entirely on label quality and
  volume from Layer 2.
