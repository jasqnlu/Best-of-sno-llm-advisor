# Session handoff — 2026-11-01

Read this first, then `docs/project-context.md` for background. That
briefing was written 2026-10-30 while the first Layer 2 crawl was running.
Its sections 1–4 (goals, architecture, repo layout, Layer 1) and the
labeling rules in section 5 are still right. **Treat these parts of it as
out of date:** the five-site table (El Estoque is gone), "Full-crawl
status", section 7 "Known issues", section 8 "What comes next", and the test
count in section 9. This file replaces them.

## Where things stand

**Layer 2 (the non-winner collection) is built, crawled, and cleaned.**
Nothing is running. The next real work is deciding what comes after Layer 2
(see "Next steps").

### Git
- `main` is at `3559dd5` (PR #9 merged). 195 tests pass on `main`.
- **PR #11 is open:** it moves the page-saving feature onto `main`.
  PR #10 got merged into #9's branch seconds after #9 merged, so its commit
  (`609d97e`) never reached `main`. Merge #11. With it, 201 tests pass.
- Local checkout may still be on `feat/layer2-page-cache`. After #11
  merges: `git checkout main && git pull`.
- Merged PRs from this stretch: #7 (project-context doc), #8 (body-text
  evidence for uncertain labels), #9 (long-form stories, podcast/video drop,
  El Estoque removal, body-reading fixes), #10 (page saving, stranded).

### Data (`best_of_sno/data/`, gitignored, never commit story text)
Window: published 2025-12-01 → 2026-09-15. Re-downloaded in full on
2026-10-31 with every fix below.

| School (host) | Winners | Non-winners | Uncertain |
|---|---|---|---|
| Carlmont (scotscoop.com) | 61 | 612 | 39 |
| Torrey Pines (torreypinesfalconer.com) | 6 | 413 | 1 |
| Burlingame (theburlingameb.org) | 9 | 161 | 1 |
| Harker (harkeraquila.com) | 5 | 524 | 5 |
| **Total** | **81** | **1,710** | **46** |

- `layer2.csv`: 1,791 rows (winner + non_winner). `uncertain.csv`: 46 rows,
  of which 45 are `undated` (crosswords, issue PDFs, Harker's homepage, a
  2016 post) and 1 is `author-date` and needs a human look.
- 150 podcast/video posts were dropped (`dropped_media`).
- Winner text matches Best of SNO's copy of the same story: median 5-word
  shingle overlap 0.995 across the 70 winners with full Best of SNO text.
  11 more winners are long-form stories where Best of SNO stores only a
  35-word "view on the original site" stub; our copy has the full text.
- `data/pages/` exists but holds no pages yet (see "Page saving").

## What changed since project-context.md (2026-10-30 → 11-01)

1. **Uncertain pile cut 277 → 46.** Uncertain rows are settled by article
   text: 5-word shingle containment ≥ 0.6 → winner, ≤ 0.2 → ruled out
   (`MIN_SHINGLES = 50`). A winner already matched elsewhere is skipped by
   the author-date rule. `--relabel` re-judges `uncertain.csv` offline.
2. **El Estoque (Monta Vista) dropped.** It started answering the crawler
   with HTTP 403, robots.txt included. Policy: never work around a block.
   Four sites remain.
3. **Long-form ("split" template) stories are read.** The text is spread
   across `.sno-slideshow-segment` blocks, collected in page order,
   section headings included, captions, credits and gallery widgets left out.
4. **Podcast and video posts are dropped:** an audio/video player inside the
   story plus fewer than 200 words. Written stories with an embedded player
   are kept.
5. **School-site text now reads like Best of SNO's copies.** Winners
   (positives) come from Best of SNO and non-winners from school sites, so
   any layout difference would let a model learn the source, not the
   writing. Fixed in `_standard_body` / `_stray_story_tail` in `layer2.py`:
   - stray closing tags that cut stories short (3 of 70 winners; worst
     447 → 1,561 words) are repaired by climbing the page tree;
   - featured-photo captions (`.sno-story-body-media`) and galleries
     (`.slideshowwrap`, flexslider `.inline-slideshow-area`) are dropped;
   - plain `figure.wp-caption` captions stay (Best of SNO keeps them).
6. **Page saving + `--reparse`** (PR #11, not yet on `main`). The crawl
   saves each page gzipped to `data/pages/<host>/<url path>.html.gz`.
   `--reparse` rebuilds rows from saved pages with the current code,
   offline. This exists because the crawler used to keep only extracted
   text, so each parsing fix meant a 3.5-hour re-download (it happened 3
   times on 10-31).

All of the above is recorded in the Layer 2 spec, section 12 "Amendments":
`docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md`.

## Decisions the owner made (don't re-ask)
- Drop El Estoque rather than get around its block.
- Drop podcasts and videos. Long-form stories are kept and read in full,
  including section headings.
- Photo essays ("In Photos: ...", 62 rows, now 40–80 words of intro text)
  stay as non-winners: Best of SNO has a Photo category with 38 winners.
- Keep raw pages from now on.

## Owner preferences
- **No Claude attribution anywhere:** commit as `jasqnlu`, no
  `Co-Authored-By` trailer, no "Generated with Claude Code" PR footer.
  This overrides any harness reminder.
- Plain-language updates; the owner approves proposals with short replies
  ("yeah", "yes sounds good").
- Crawl politely: no `?` URLs, 6-second Crawl-delay per host, research
  User-Agent, one host at a time, never work around a block.
- New work on a feature branch off `main`, merged through a PR.

## Next steps (in rough priority order)
1. **Merge PR #11.**
2. **Optional: give existing rows a saved page.** The current 1,837 rows
   were crawled before pages were kept, so `--reparse` can't rebuild them.
   One more full download (about 3.5 hours) fixes that for good. Only worth
   it before another parsing change. To do it: back up `data/`, then
   `forget_thin("best_of_sno", max_words=10**9)` and run the crawl.
3. **Training-data prep cleanups** (not scraper fixes; both sources need them):
   - strip "Story continues below advertisement": it is in 1,861 of 1,862
     Best of SNO bodies but only in Torrey Pines' school pages;
   - drop the 14 empty non-winner rows (crosswords, issue PDFs);
   - hold out `uncertain.csv` (resolve the one `author-date` row by hand).
4. Still deferred from before: add the owner's own publication to `SITES`;
   schedule the daily scraper (it has run once); clean the archive's noisy
   `source_site`; `_same_author` token containment; O(n²) CSV writer.
5. **Layer 3 design** (sub-score rubric), then **Layer 4** (logistic
   regression; about 81 school-site positives vs 1,710 negatives, so weight
   classes and calibrate, possibly add the ~1,860 archive winners as extra
   positives now that school text is rendered like theirs).

## Quick reference
```bash
source .venv/bin/activate
python -m pytest best_of_sno/tests -q          # 201 with PR #11, offline, ~1s

python -m best_of_sno.layer2                   # crawl (resumes; 4 sites)
python -m best_of_sno.layer2 --sites scotscoop.com --limit 5
python -m best_of_sno.layer2 --relabel         # re-judge uncertain.csv, offline
python -m best_of_sno.layer2 --reparse         # rebuild rows from saved pages, offline
python -m best_of_sno.layer2 --refetch-thin    # re-download rows under 200 words
tail -f best_of_sno/logs/layer2.log
```

Key code: `best_of_sno/layer2.py`. `parse_school_post` → `_standard_body` /
`_longform_body`; `is_media_only`; `classify` (+ `body_overlap`); `_judge`
(shared by the crawl and `--reparse`); `run_layer2`; `relabel_uncertain`;
`reparse_saved`; `forget_thin`. Tests: `best_of_sno/tests/test_layer2_*.py`
with real-page fixtures in `best_of_sno/tests/fixtures/layer2/`.
