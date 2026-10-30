# Layer 2 — handoff prompt for a new chat

Paste the block below into a fresh chat, and attach (or point it at) the
approved design doc:
`docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md`.

The design is already settled (brainstormed + builder-checked on
2026-10-29). The new chat's job is plan → build, not re-design.

---

```
I'm building Layer 2 of a "Best of SNO LLM Advisor." The design is already
approved — it's in the attached file (also at
docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md
in the repo). Do NOT re-brainstorm or re-litigate the design; it's settled.

Repo: /Users/jasonlu/Desktop/Best-of-sno-scraper/Best-of-sno-llm-advisor
Branch: start a feature branch off main (main is clean, all tests pass).

What I want from you, in order:
1. Read the design doc in full, plus the two shipped modules it reuses:
   best_of_sno/backfill.py and best_of_sno/scraper.py (and their tests under
   best_of_sno/tests/). Layer 2 imports the backfill's sitemap enumeration,
   fetch, and post parser — it is mostly re-pointing proven machinery at 5
   new SNO-platform sites, not new scraping logic.
2. Use the superpowers:writing-plans skill to produce an implementation plan
   at docs/superpowers/plans/, decomposed into TDD tasks with offline
   fixtures (mirror the backfill's plan/test style). Show me the plan and
   let me approve it before any code.
3. Then execute it with superpowers:executing-plans (Native — you implement
   each task yourself with TDD, one fresh whole-branch review at the end).

Non-negotiables carried from the design (the builder-check already caught
these — make sure the plan honors them):
- Winner corpus = archive.csv ∪ new.csv ∪ old.csv, NOT archive.csv alone
  (a winner the daily scraper caught lives only in new/old; matching archive
  alone would mislabel it a non-winner).
- post_id_from_url / parse_post must take an optional host= param (default
  "bestofsno.com" so backfill output stays byte-identical); Layer 2 needs
  its OWN wider-column writer — reusing backfill.append_rows silently drops
  label/matched_id/source_site. Quoting = QUOTE_MINIMAL to match archive.csv.
- Undated articles (empty published) → uncertain.csv with reason="undated",
  never silently filed as non_winner.
- Labeling = exact normalized-title match → winner / non_winner / uncertain;
  uncertain.csv is held out of training for manual review.
- Strict robots compliance: no "?"-URLs, Crawl-delay 6s per host, the
  existing research User-Agent. Resumable via layer2_state.json.
- The backfill's own tests must still pass unchanged after any refactor.

Outputs: best_of_sno/data/layer2.csv, uncertain.csv, layer2_state.json
(all gitignored). CLI: python -m best_of_sno.layer2 with
--since/--until/--sites/--limit/--dry-run/--delay.

Confirm you've read the doc and both modules, then show me the plan.
```

---

## Quick facts the new chat may want (all verified 2026-10-29)

- Five sites, all SNO `snoflex` platform, same sitemap/robots as bestofsno:
  scotscoop.com (Carlmont), elestoque.org (Monta Vista),
  torreypinesfalconer.com (Torrey Pines), theburlingameb.org (Burlingame),
  harkeraquila.com (The Harker School).
- Scale: ~4,000 in-window articles total (~818 on Scotscoop alone),
  ~100 winners across the 5 schools, ~6–7h polite crawl.
- `archive.csv` is already on disk (~1,622 winners, Jan–Oct 2026).
- Window: published 2026-01-01 → 2026-10-10 (customizable).
