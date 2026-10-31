# Best of SNO LLM Advisor — Project Context

*Snapshot: 2026-10-30, evening. Repo: `github.com/jasqnlu/Best-of-sno-llm-advisor`, branch `main` at `0a17372`.*

This file is a self-contained briefing. You can paste it into a new chat, hand it to a collaborator, or use it to re-orient after time away. It covers what the project is for, what has been built, what the data looks like, what was learned the hard way, and what comes next.

---

## 1. What this project is

A newsroom tool for a high-school publication that hasn't been winning many **Best of SNO** honors. Best of SNO (`bestofsno.com`) is a daily showcase of the strongest student stories across the SNO Sites network (thousands of school newspapers on a shared WordPress platform). Being picked is a mark of quality.

The tool takes a journalist's draft and returns two things:

1. **A chance bar.** One Best-of-SNO-likeness score from 0–100%. It is built from named, explainable sub-scores, such as lede strength, sourcing depth, structure, originality and craft.
2. **Advice.** Concrete, draft-specific fixes, for example "the lede buries the human stakes; lead with the sticky-note detail". Generic writing tips don't count.

**Why:** the editor (Jason Lu, the publication's online editor) can see what winning stories have in common but can't coach every draft by hand. The tool scales that coaching and turns "what makes a story Best-of-SNO-worthy" into something measurable.

### Goals
- A growing, de-duplicated archive of Best of SNO **winning** stories (full text and metadata).
- A labeled set of **non-winning** stories from real school sites, so a model can learn the difference.
- A chance bar grounded in that labeled data, plus advice tied to the sub-scores.

### Non-goals
- Not a public product; it is for internal newsroom use.
- Not republishing anyone's stories. Full text is stored privately for analysis only; data CSVs are gitignored and never committed.
- Not real-time. Batch jobs are fine.

### Anti-goals (a failure even if it "works")
- **A confident number with nothing behind it,** such as an LLM guessing a percentage. If the score isn't grounded in labeled winner vs. non-winner data, no score is better.
- **Generic advice** that isn't specific to the draft in front of it.
- **Impolite scraping.** Ignoring robots.txt or crawl-delay gets us blocked and is disrespectful to other students' work.
- **A poisoned negative class.** A real winner labeled "non-winner" teaches the model that a winner is a loser. This is the worst data failure in the project, and much of Layer 2's design exists to prevent it.

---

## 2. Architecture: four layers

```
Best of SNO feed + sitemaps ──(Layer 1)──▶ winners corpus (archive/new/old CSV)
                                                   │  the answer key
5 school news sites ──(Layer 2 crawl)──▶ articles ─┤
                     auto-labeled winner / non_winner / uncertain
                                                   ▼
                      (Layer 3) sub-score rubric ──▶ named sub-scores per article
                                                   ▼
                      (Layer 4) logistic regression ──▶ chance bar %
                                                   ▼
                      Advice = Claude at inference, grounded on the score
                               + retrieved similar winners
```

| Layer | What | Status |
|---|---|---|
| 1a | Daily RSS scraper of new Best of SNO winners | **Built and merged** (PR #1). Ran once on 2026-10-28; **not yet scheduled** (no cron or launchd entry). |
| 1b | One-time historical backfill of winners via sitemaps | **Built and merged** (PRs #2, #3). Corpus now covers 2025-12-01 → 2026-10-30. |
| 2 | Crawl 5 school sites, auto-label each article against the winners corpus | **Built and merged** (PRs #4, #5, #6). **Full crawl running now.** |
| 3 | Sub-score rubric (the "features") | Not started; needs its own design. |
| 4 | Chance-bar model (logistic regression on sub-scores) | Not started. |

### A design pivot to know about
The original plan (2026-10-28) had Layer 3 as a **QDoRA fine-tuned advice LLM** on Google Colab. During Layer 2 brainstorming (2026-10-29) this was deliberately cut: distilling Claude's critiques into a small model gives a weaker copy of Claude. The new plan:
- **Lead with the empirical chance score** (Layer 4), the part that needs real labeled data.
- **Advice = Claude at inference time,** grounded on the Layer 4 score and its sub-scores, plus retrieved archive winners as examples.
- Layer 3 is now mainly about **defining and producing the sub-scores** that feed the logistic regression. How they're produced (Claude scoring with a rubric, hand-built text features, or both) is still open.

Why logistic regression on a handful of sub-scores: the "needs lots of data" burden goes to the LLM, which already understands English. The fitted model then has only about 7 weights, which is feasible with roughly 100 positives. Because the probability is built from named sub-scores, the chance bar doubles as the advice: "lede 3/10 is what's dragging you down."

---

## 3. Repository layout

```
best_of_sno/
  scraper.py      397 lines   Layer 1a: daily RSS scraper
  backfill.py     409 lines   Layer 1b: historical sitemap backfill
  layer2.py       518 lines   Layer 2: school-site crawl + labeler
  requirements.txt            requests, feedparser, beautifulsoup4, defusedxml
  data/   (gitignored)        archive.csv, new.csv, old.csv, state.json,
                              backfill_state.json, layer2.csv, uncertain.csv,
                              layer2_state.json
  logs/   (gitignored)        scraper.log, backfill.log, layer2.log
  tests/                      17 test files, 144 tests, all passing (<1s, fully offline)
    fixtures/                 saved real HTML/XML/RSS from the live sites
docs/superpowers/
  specs/   2026-10-28-best-of-sno-advisor-design.md          master design (all layers)
           2026-10-29-layer1-historical-backfill-design.md
           2026-10-29-layer2-school-site-nonwinners-design.md (§11 = live-data amendments)
  plans/   one TDD implementation plan per feature
  layer2-handoff-prompt.md
docs/project-context.md       this file
```

**Stack:** Python 3.14 (Homebrew) in `.venv`, stdlib `csv` (no pandas), `requests`, BeautifulSoup, `defusedxml` for sitemap XML, `feedparser` for RSS. pytest. Runs on a macOS laptop.

**Workflow conventions:**
- Every feature follows the same path: design spec → implementation plan → TDD execution (failing test first) → final whole-branch review → PR.
- Commits are authored by **jasqnlu** with **no Claude attribution trailers**, and PRs carry no "Generated with Claude Code" footer. This is an explicit standing instruction from the owner.
- Feature branches go to PRs against `main`. Watch out for stacked PRs: #5 originally merged into a docs branch rather than `main`, and #6 fixed that.

### Git history (33 commits, 6 merged PRs)
| PR | Content |
|---|---|
| #1 | Layer 1 daily scraper: parsing, polite fetch, atomic CSV writes, rotation, state, CLI, CSV formula-injection guard |
| #2 | Historical backfill; the daily scraper treats backfilled ids as already seen |
| #3 | Backfill skips winners already in new.csv/old.csv, so each winner lives in exactly one file |
| #4 | Layer 2 design + handoff prompt |
| #5 | Layer 2 implementation: host-parameterized helpers, Yoast sitemaps, per-site parse tests, labeler, writers, orchestration, CLI, crawl-delay fixes |
| #6 | Fixes from live trial runs: date-only bylines, republish-lag date matching, new crawl window, corpus-coverage guard, spec amendments |

---

## 4. Layer 1: the winners corpus (the answer key)

### 1a. Daily scraper (`python -m best_of_sno.scraper`)
- Reads `https://bestofsno.com/feed/`, which holds about 10 items with full body text and a `By Author, School` byline.
- Each run rotates the previous `new.csv` into `old.csv`, writes newly seen stories to `new.csv`, and records ids in `state.json`.
- Crash safety: writes `*.tmp` then renames, and saves state last.
- Flags: `--dry-run`, `--no-rotate`.
- **Gap:** it has only run once (2026-10-28, 10 stories) and nothing schedules it. The feed shows only about 10 stories, so missed days lose winners unless the backfill is re-run. **To do:** add a launchd job, or periodically re-run the backfill, which is idempotent and resumable.

### 1b. Historical backfill (`python -m best_of_sno.backfill --since YYYY-MM-DD`)
- Enumerates `bestofsno.com/wp-sitemap.xml` → `wp-sitemap-posts-post-N.xml`, filters by `lastmod`, fetches each post page at 6s intervals, and parses the `.sno-story-byline` (`By Author, School • Month DD, YYYY`).
- Ids match the feed's guid (`https://bestofsno.com/?p=<n>`), so dedup works across all three files.
- Resumable via `backfill_state.json`. `--limit`, `--dry-run`, `--delay`.

### Corpus as of today
- `archive.csv`: **1,862 winners**, published **2025-12-01 → 2026-10-30**.
- `new.csv`: 10 (from 2026-10-28). `old.csv`: does not exist yet.
- **12 columns** shared by every corpus file: `id,url,title,published,categories,author,school,summary,body,word_count,source_site,scraped_at`.
- School is blank for 454 archive rows: multi-author bylines leave it empty by design.
- Winners for the five Layer 2 schools: **114 total** (Carlmont 70, Monta Vista 17, Torrey Pines 10, Burlingame 9, Harker 8). That is the ceiling on positive matches.

**Important fact: Best of SNO's `published` date is the *republish* date, not the school's original date.** It runs **3–40 days later (median 18)** than the school site, measured on 17 Carlmont winners. Never match dates for equality.

**Known weakness:** archive `source_site`, inferred from image hosts in the body, is noisy. 1,147 rows are blank and the top non-blank value is `public.flourish.studio`, a chart-embed host rather than a school. Fix this before using `source_site` to pick new schools to crawl.

---

## 5. Layer 2: school-site crawl + auto-labeling (`python -m best_of_sno.layer2`)

### Purpose
Collect the **negative class**: real high-school journalism that did *not* win. Without negatives, a classifier can't answer "how likely is this to win?".

### Sites (all SNO `snoflex` WordPress)
| Host | School |
|---|---|
| scotscoop.com | Carlmont High School |
| elestoque.org | Monta Vista High School |
| torreypinesfalconer.com | Torrey Pines High School |
| theburlingameb.org | Burlingame High School |
| harkeraquila.com | The Harker School |

The owner's own publication is meant to be added as a source too; it isn't in `SITES` yet. The engine is site-agnostic, so adding a site is mostly a one-line table entry plus a fixture test.

### How it works
1. **Coverage guard.** It refuses to run if the winners corpus is empty, or if `--since` is more than 7 days before the corpus start. Otherwise winners from the gap would silently be labeled non-winners.
2. **Enumerate** each host's sitemaps: core `wp-sitemap-posts-post-N.xml` *or* Yoast `post-sitemapN.xml` (Harker).
3. **Fetch** each post politely:
   - no `?` URLs, 6s `Crawl-delay` per host, including between sitemap requests;
   - research User-Agent with a contact email;
   - one host at a time.
4. **Parse** with the backfill parser, plus school-site fallbacks:
   - date from the byline's `.time-wrapper` or `.sno-story-date`;
   - " – Site Name" stripped from titles;
   - date-only bylines don't become authors.
5. **Ids:** `https://<host>/?p=<n>` for numeric permalinks, otherwise the canonical URL. El Estoque's `/2026/01/13/...` date permalinks would otherwise all collide on `?p=2026`.
6. **Label** each article against that school's winners from `archive.csv ∪ new.csv ∪ old.csv`. All three files are needed because each winner lives in exactly one of them. Rules, in order:
   1. No date → **uncertain / `undated`**.
   2. Exactly one exact normalized-title match → **winner** if the dates fit the republish lag (corpus date −1 to +60 days after the school date). Otherwise **uncertain / `title-ambiguous`**, for example a recurring column title.
   3. Several exact matches → the one with matching author and date, else `title-ambiguous`.
   4. Title similarity ≥ 0.90 (`difflib`) → **uncertain / `title-nearmatch`**: probably a reworded republish.
   5. Same author *and* a corroborating date as some winner → **uncertain / `author-date`**: possibly a heavily retitled winner.
   6. Otherwise → **non_winner**.
7. **Write:** confident rows go to `layer2.csv`; ambiguous rows go to `uncertain.csv` with the candidate winner's title and URL side by side for human review. Writes are atomic and use the CSV formula-injection guard.
8. **Resume:** a checkpoint in `layer2_state.json` plus ids already in the output files, so an interrupted run continues where it stopped.

Title normalization: unescape HTML, turn Unicode punctuation into spaces, lowercase, collapse whitespace.

### Crawl window: published **2025-12-01 → 2026-09-15**
- **Start:** 4 of 9 January-dated Carlmont winners were first published on Scot Scoop in December, so starting at Jan 1 would miss winners.
- **End:** the run date minus the 40-day maximum lag, so every included article has had time to win. Articles published after the end date are dropped, not labeled non-winner.
- Both the winners and non-winners come from the same window, so the model can't learn *when* a story ran instead of *how good* it is.

### Outputs
- `layer2.csv`: the 12 corpus columns + `label` + `matched_id`. `source_site` is the host here and is accurate.
- `uncertain.csv`: the same columns + `reason`, `candidate_title`, `candidate_url`. **Held out of training until a human resolves each row.**

### Leakage rule
Every Layer 2 row, winners included, carries the **school-site** body text, never the bestofsno.com copy. Otherwise the model could learn which site rendered the page instead of how good the article is.

### Full-crawl status (running in the background since 2026-10-30 15:56)
| Site | Progress | Winners | Non-winners | Uncertain |
|---|---|---|---|---|
| Scot Scoop | **done** (1,279 checked; the rest out of window) | 64 of 70 | 555 | 131 (92 author-date, 39 undated) |
| El Estoque | ~503 / 690 at 19:20 | 12 so far | 328 | 57 |
| Torrey Pines | pending | | | |
| Burlingame | pending | | | |
| Harker | pending | | | |

Expected finish: about 21:30–22:00. Log: `best_of_sno/logs/layer2.log`.

**Early concern:** the `author-date` rule is noisy. A prolific staff writer with one win sends many of their other articles in the 60-day window to `uncertain.csv` (92 at Scot Scoop alone). Next step: sample those rows. If nearly all are true non-winners, tighten the rule so it doesn't flood manual review. Options include a narrower lag window or requiring some title similarity too.

---

## 6. Lessons learned from live data

The design docs made assumptions that turned out false when tested against the real sites. Each became a test plus a fix.

1. **The five sites aren't uniform.** They use slug permalinks, date permalinks, or numeric permalinks; WordPress core or Yoast sitemaps; dates in the byline or in `.sno-story-date`; titles with or without a " – Site Name" suffix. Bylines on school sites read "Name, Staff Role", not "By Name, School".
2. **Best of SNO republishes 3–40 days later** with a new date. Exact-date matching never fired; it was replaced with a lag window.
3. **A lone exact title match isn't proof.** Recurring column titles repeat, so the dates must also corroborate.
4. **Old articles with date-only bylines** were being filed as "undated". Fixed by reading the byline's own `.time-wrapper`.
5. **The crawl window must not start before the winners corpus.** This led to backfilling winners from December and adding the coverage guard.
6. **Crawl-delay applies to sitemap requests too,** not just post fetches.
7. **The "Best of SNO" badge isn't in the school-site HTML** (it is JS-injected or doesn't exist). Cross-referencing against the archive is the only labeling route.

---

## 7. Known issues and deferred items

- **`author-date` uncertain flood:** see §5. Decide after the crawl finishes.
- **`_same_author` uses token containment,** so "Ada Lee" matches "Ada Lee Smith". This is minor and only affects uncertain routing.
- **The Layer 2 writer rewrites the whole CSV per row,** which is O(n²). Fine at about 4k rows; revisit if the site list grows a lot.
- **Dry-run candidate counts are taken before dedup,** so they overstate slightly.
- **Posts dropped for being after `--until` are marked done.** Extending the window later means clearing those ids from `layer2_state.json`.
- **Some rows have `word_count == 0`** (crosswords, photo galleries, embeds). Filter them in Layer 4.
- **The daily scraper isn't scheduled** (§4).
- **The archive's `source_site` is noisy** (§4).
- **The owner's own publication isn't crawled yet** (§5).

---

## 8. What comes next

1. **Finish the Layer 2 crawl** and review the results:
   - per-school counts, compared with the 114-winner ceiling;
   - how many winners went unmatched, and why;
   - the size and makeup of `uncertain.csv`.
2. **Tune the uncertain rules** (mainly `author-date`), then **manually resolve** the remaining uncertain rows.
3. **Add the owner's publication** to `SITES`, and consider more strong programs chosen from the winners archive, once `source_site` is cleaned.
4. **Schedule the daily scraper** (launchd), or set up a periodic re-backfill.
5. **Layer 3 design:**
   - choose the sub-score rubric (about 6–8 named dimensions);
   - decide how each is produced (Claude rubric scoring vs. computed text features);
   - validate that the sub-scores separate winners from non-winners at all.
6. **Layer 4:** logistic regression on the sub-scores.
   - Expect heavy class imbalance: roughly 100 positives vs. thousands of negatives. Use class weighting and probability calibration.
   - The score should read as "how Best-of-SNO-like", not as a verdict.
   - Consider adding the ~1,860 archive winners as extra positives, weighed against the leakage risk (their text is the bestofsno.com copy).
7. **The advisor itself:**
   - Claude reads a draft and gets its sub-scores and chance bar, plus a few retrieved similar winners;
   - it returns specific advice tied to the weakest sub-scores.

---

## 9. Quick reference

```bash
# environment
source .venv/bin/activate          # Python 3.14
python -m pytest -q                # 144 tests, offline, <1s

# Layer 1
python -m best_of_sno.scraper [--dry-run] [--no-rotate]
python -m best_of_sno.backfill --since 2025-12-01 [--limit N] [--dry-run] [--delay 6]

# Layer 2 (defaults: --since 2025-12-01 --until 2026-09-15, all 5 sites)
python -m best_of_sno.layer2 [--sites scotscoop.com,elestoque.org] [--limit N] [--dry-run]
tail -f best_of_sno/logs/layer2.log
```

**Politeness constants everywhere:**
- no URLs containing `?`;
- `Crawl-delay: 6` seconds per host;
- User-Agent `BestOfSNO-research-scraper (<contact email>)`.

**Data never leaves the laptop:** `best_of_sno/data/*.csv` and the state files are gitignored for copyright reasons.
