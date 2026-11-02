# Layer 3: sub-score rubric and scorer — design

Date: 2026-11-01. Background and the full discussion are in
`docs/layer3-brainstorm-context.md` (branch `docs/layer3-brainstorm-context`).
This file records what was built and decided.

## What Layer 3 does

A scorer reads one story and gives it seven 1–5 scores, each with a short
quote from the story as evidence, and tags the story type. Layer 4 turns
those scores into the chance bar. The same pinned scorer must grade the
training stories and every real draft, or the chance bar drifts.

## Rubric [owner approved, 2026-11-01]

Seven dimensions, each with a five-level anchor table (full text in
`best_of_sno/scorer.py`, `DIMENSIONS`):

| Key | Measures |
|---|---|
| lede | the opening pulls you in and points at the stakes |
| sourcing | people with a direct stake; a range of viewpoints; named over anonymous |
| quotes | quotes reveal feeling or insight, not logistics |
| focus | stays on one angle; every section serves it |
| depth | facts, data, documents, scenes beyond interviews |
| significance | why readers should care; stakes beyond the school |
| craft | clear sentences, flow between sections, a real ending |

Story type is tagged in the same call (feature, news, sports, opinion,
profile, review, other). Length is not a rubric score: `long_enough` is a
plain 500-word check.

## Pinned scorer setup

Ollama, `temperature` 0, `seed` 0, `num_ctx` 8192, thinking off
(`"think": false` on every request), JSON-schema output. A reply that
doesn't validate is recorded as an error, never as a score. A prompt that
fills the context window is an error (Ollama would silently cut it). The
longest feature (4,603 words) uses 6,657 tokens.

## Scorer trial (2026-11-01)

60 stories: 30 winning features and 30 non-winning features matched on
length and school. Each scorer got the same rubric. Claude scored through
Claude Code subagents as the quality reference (no API key; not usable for
live scoring). `python -m best_of_sno.layer3_trial compare`:

| | Claude | Gemma 12B | Gemma E4B |
|---|---|---|---|
| AUC, total score (0.5 = coin flip) | 0.67 | 0.62 | 0.65 |
| Evidence quotes really in the story | 100% | 80% | 50% |
| Rank agreement with Claude, total | – | 0.67 | 0.49 |
| Rank correlation with word count, total | 0.21 | 0.52 | 0.28 |
| Median seconds per story (RTX 2060 Super) | – | 29.5 | 5.5 |

Both Gemma sizes score generously (about 29/35 vs Claude's 22/35).
Focus separates winners worst for every scorer (AUC 0.43–0.57).

## Decisions [owner, 2026-11-01]

1. **No owner hand scores.** The owner doesn't have time to grade; Claude's
   trial scores stand in as the reference. The hand-scoring page
   (`layer3_trial handscore-page` / `import-owner`) stays available.
2. **Scorer: `gemma4:12b`.** It tracks Claude far better than E4B and makes
   up fewer evidence quotes. E4B's small AUC edge is within noise on 60
   stories.
3. **Length counts when it's earned.** The owner's view: length shows
   effort, as long as it serves the story's point. So:
   - the rubric judges whether length is earned (Focus: "nothing could be
     cut without loss"; Depth: reporting beyond interviews);
   - word count goes into Layer 4 as its own input, so the data decides how
     much it adds on top of the seven scores;
   - 12B's lean toward longer stories is accepted; no prompt change or
     re-run.

## Full scoring run

`python -m best_of_sno.layer3 score gemma4:12b`, then `export` to
`data/layer3_scores.csv` (one row per story: label, source, word count,
`long_enough`, story type, the seven scores, total).

Scope is the owner's chance-bar scope, in-depth features only (733 stories):

| Source | Label | Stories |
|---|---|---|
| training.csv features | winner | 60 |
| training.csv features | non_winner | 155 |
| archive.csv features | winner | 518 |

Archive features skipped: 60 that are the same story as a training winner,
and 53 "view on the original site" stubs of 35–55 words (nothing in the
archive sits between 60 and 300 words; the cut is 100). Archive bodies get
the same `clean_body` as training rows. The 60 trial stories reuse their
trial scores.

### Results (run 2026-11-01, 733 stories, 0 errors)

About 5.5 hours on the RTX 2060 Super, including ~43 minutes of cooling
pauses (the run paused at 80°C GPU and resumed at 70°C; peak 84°C).
AUC = chance a winner outscores a non-winner. "Training" compares the 60
school-site winners with the 155 school-site non-winners; "all" adds the
518 archive winners.

| | Training winners avg | Archive winners avg | Non-winners avg | AUC training | AUC all | Rank corr. with length |
|---|---|---|---|---|---|---|
| lede | 3.62 | 3.48 | 2.85 | 0.68 | 0.65 | 0.29 |
| sourcing | 4.32 | 4.08 | 3.66 | 0.70 | 0.63 | 0.49 |
| quotes | 4.30 | 4.14 | 3.73 | 0.70 | 0.65 | 0.51 |
| focus | 4.27 | 4.41 | 4.19 | 0.53 | 0.59 | 0.17 |
| depth | 4.20 | 3.68 | 3.31 | 0.81 | 0.65 | 0.57 |
| significance | 4.50 | 3.86 | 3.49 | 0.83 | 0.65 | 0.52 |
| craft | 3.72 | 3.64 | 3.22 | 0.69 | 0.67 | 0.45 |
| **total** | 28.92 | 27.29 | 24.45 | **0.81** | **0.71** | 0.55 |
| word count alone | 1,678 | 1,231 | 1,110 | 0.77 | 0.62 | – |

- The total separates winners better than word count alone (0.81 vs 0.77
  on training; 0.71 vs 0.62 with archive winners), so the scores carry
  information beyond length.
- Significance and depth separate school-site winners best. Focus barely
  separates them (0.53) and is the least length-driven: the first
  candidate for rewording.
- Archive winners score below the four schools' winners, mostly on depth
  and significance, and are shorter. Layer 4 should check whether
  that gap matters.
- Story-type tags: feature 385, profile 249, news 95, other 4. Every story
  was filed as a feature, so the tag mostly splits features from profiles.

## Open for Layer 4

- `source` must not be a model input: every archive row is a winner.
- Non-winners are 155 of 733, so weight the classes and calibrate.
- Focus may need rewording if it still doesn't separate winners there.
- The brainstorm's consistency check (score about 30 stories twice and
  compare) hasn't been run. With temperature 0 and a fixed seed, repeats
  should match exactly.
