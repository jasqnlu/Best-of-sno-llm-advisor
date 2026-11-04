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
| focus | a central point stated early (a nut graf), and sections that move it forward (reworded 2026-11-03; see below) |
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

## Layer 4: the chance bar (built 2026-11-01)

`python -m best_of_sno.layer4 evaluate` / `fit` → `data/layer4_model.json`.

- Logistic regression on the seven scores plus log word count, written in
  plain Python (no numpy/scikit-learn). `source` is never an input: every
  archive row is a winner.
- Winners and non-winners weighted equally; L2 penalty 1.0 on
  standardized inputs.
- The percentage is shifted to the owner's schools' real feature win rate,
  60 of 215 = 27.9%, so an unremarkable story reads as about 28%, not 50%.
- Trained on all 733 stories (archive winners included).

**Held-out results** (5-fold × 10):

| Model | AUC within one school | AUC across the 4 schools |
|---|---|---|
| scores + length (chosen) | 0.64 | 0.80 |
| scores only | 0.64 | 0.80 |
| length only | 0.62 | 0.77 |
| scores + length, trained on the 4 schools only | 0.61 | 0.84 |

**The across-school number is misleading.** 54 of the 60 school-site
feature winners are Carlmont, and "is it Carlmont" alone reaches 0.82.
Only the within-school AUC (Carlmont, the one school with enough of both)
shows whether the model judges writing, and there it is barely ahead of
length. Probable cause: 12B scores bunch at 4–5. Even Claude reached only
0.67 on length- and school-matched pairs in the trial.

**Decision [owner, 2026-11-01]: show a band, not a percentage.**
`chance_band`: Low under 20%, Medium 20–40%, High 40% and up. Held out
on the owner's schools, these won 2% (64 stories), 31% (95) and 54% (56).
The seven scores and the advice are the main output. The fine-tuned
advice model is the planned route to sharper scoring.

## Consistency check (run 2026-11-02 on the PC)

`python -m best_of_sno.layer3 consistency gemma4:12b`: 30 stored stories
(seed 0) scored again with the same setup (gemma4:12b `6114515d63c1`,
Ollama 0.40.13, temperature 0, seed 0).

| | Result |
|---|---|
| Stories with all scores and story type the same | 22 of 30 |
| Single scores that changed | 8 of 210, every one by 1 point (6 up, 2 down) |
| Story type changed | 2 (profile → feature, news → feature) |
| Evidence quotes word-for-word the same | 9 of 30 |
| Errors | 0 |

Changes: sourcing 3→4; lede 4→5, focus 4→5, significance 3→4 (one
story); depth 2→3; lede 2→3; significance 5→4; lede 4→3.

**Reading:** Ollama is not fully repeatable on this machine even with
temperature 0 and a fixed seed (likely GPU math and batching). The noise is
small (about 4% of scores, never more than 1 point; 30 stories is too
few to say the 6-up/2-down tilt is real), but on scores that bunch at 4–5 a 1-point wobble is a real part
of the spread Layer 4 learns from. Averaging two runs per story would
cut it.

## Focus rewording trial (run 2026-11-03 on the PC)

Focus v1 gives nearly every story a 4 or 5 and gets a negative Layer 4
weight (−0.18). `focus-v2` (`scorer.VARIANTS`) asks for a central point
stated early (a nut graf) and sections that move it forward; a 4 now
requires that at most one section could be cut. Run with
`python -m best_of_sno.layer3_trial run gemma4:12b --variant focus-v2` on
the same 60 trial stories and pinned setup.

| Focus | v1 | v2 |
|---|---|---|
| Scores 2 / 3 / 4 / 5 | 0 / 1 / 40 / 19 | 1 / 19 / 38 / 2 |
| Winner avg vs non-winner avg | 4.23 vs 4.37 | 3.77 vs 3.60 |
| AUC (winners vs matched non-winners) | 0.43 | 0.58 |
| Rank agreement with Claude's Focus | 0.11 | 0.24 |
| Rank correlation with word count | 0.37 | 0.38 |
| Rank correlation with the other six scores | 0.53 | 0.70 |

The other six scores barely moved (49–54 of 60 identical per dimension;
their AUCs within ±0.03). Total AUC 0.62 → 0.64.

**Reading:** v2 fixes the ceiling and now points the right way, but 60
stories is a small test, and v2 overlaps more with the other scores, so
its own weight in Layer 4 may stay small.

**Decision [owner, 2026-11-03]: adopt v2.** It is now the pinned Focus
wording in `DIMENSIONS`; the first wording stays in `VARIANTS` as
`focus-v1`. All 733 features are re-scored with two runs each and the
export averages them. The trial's v2 scores used the identical prompt, so
they serve as run 1 for those 60 stories. The v1 scores are kept beside
the data as `*.focus-v1.*` files.

## Re-score with focus-v2, two runs averaged (run 2026-11-04 on the PC)

`layer3 score gemma4:12b`, then `--run 2`, then `export`: all 733 features
with the pinned focus-v2 wording (gemma4:12b, Ollama 0.40.14 after an
auto-update mid-run, same pinned setup). Run 1 reused the 60 trial scores
(identical prompt). About 5 hours per run, 0 errors. GPU mostly 64–70°C, with
short spikes to 80–85°C at the start of some stories (brief thermal throttling,
never sustained). The v1 table above is kept for comparison; the v1 export is
`data/layer3_scores.focus-v1.csv`.

**Run 1 vs run 2:** 519 of 733 stories identical on all seven scores; 347 of
5,131 single scores changed (6.8%), 345 by 1 point and 2 by 2 points, spread
evenly across dimensions (45–59 each). This matches the consistency check
(22 of 30 identical).

**Results (two runs averaged):**

| | Training winners avg | Archive winners avg | Non-winners avg | AUC training | AUC all | Rank corr. with length |
|---|---|---|---|---|---|---|
| lede | 3.59 | 3.39 | 2.78 | 0.70 | 0.66 | 0.29 |
| sourcing | 4.29 | 3.98 | 3.66 | 0.71 | 0.60 | 0.48 |
| quotes | 4.17 | 4.02 | 3.60 | 0.71 | 0.65 | 0.50 |
| focus | 3.73 | 3.60 | 3.20 | **0.72** | **0.67** | 0.35 |
| depth | 4.10 | 3.55 | 3.24 | 0.81 | 0.63 | 0.55 |
| significance | 4.33 | 3.76 | 3.42 | 0.81 | 0.64 | 0.50 |
| craft | 3.57 | 3.51 | 3.09 | 0.70 | 0.68 | 0.47 |
| **total** | 27.78 | 25.81 | 22.99 | **0.82** | **0.71** | 0.56 |
| word count alone | 1,678 | 1,231 | 1,110 | 0.77 | 0.62 | – |

- Focus AUC 0.53 → 0.72 (training) and 0.59 → 0.67 (all), confirming the
  trial. Its averaged scores now spread: below 3 25, 3–3.5 337, 4–4.5 359,
  5 12 (v1: 446 fours and 273 fives). It now tracks length more (0.17 → 0.35)
  but still less than the other scores.
- The other six AUCs moved by at most 0.03; the total by +0.01.
- Within Carlmont only (54 winners, 40 non-winners), raw AUCs: total
  0.62 → 0.63, focus 0.48 → 0.58, word count 0.63. A bootstrap puts the
  total's 90% range at about 0.53–0.73, so within-school numbers move ±0.1
  by chance.

**Layer 4 refit** (`evaluate`, then `fit`; 5-fold × 10 held out):

| Model | AUC within one school | AUC across the 4 schools | Brier |
|---|---|---|---|
| scores + length (chosen) | 0.59 (was 0.64) | 0.75 (was 0.80) | 0.176 (was 0.166) |
| scores only | 0.59 | 0.75 | 0.176 |
| length only | 0.62 | 0.77 | 0.178 |
| scores + length, 4 schools only | 0.56 (was 0.61) | 0.82 (was 0.84) | 0.164 |

Bands, held out on the owner's schools: Low 61 stories won 5% (was 2%),
Medium 96 won 27% (was 31%), High 58 won 53% (was 54%).

Weights per standard deviation: craft +0.32, focus +0.25 (was −0.18),
quotes +0.25, lede +0.07, log words +0.07, significance +0.01, depth −0.01,
sourcing −0.02.

**Reading:** the rewording worked at the score level: Focus now points the
right way, and Layer 4 gives it the second-largest positive weight. But the
fitted model got slightly worse held out, while the raw total did not. The
drop is inside the ±0.1 chance range of the 94-story within-school test, so
it is probably noise, not damage. The model was refitted anyway, because the
old one was trained on v1 Focus scores and the pinned scorer now produces v2.
The old model is kept as `data/layer4_model.pre-focus-v2.json.bak`. The weights
moving a lot between fits (significance +0.10 → +0.01, depth +0.09 → −0.01) suggest
the seven scores overlap enough that the regression can't tell them apart. With
518 of 578 winners from the archive, the weights may also mostly learn
"archive vs school story". That is the next thing to check.

## Still open

- ~~Focus may need rewording~~: done (focus-v2, see above).
- ~~Average two scoring runs per story~~: done (2026-11-04).
- Layer 4 barely beats length within one school. Try training on the four
  schools' stories only, fewer inputs (e.g. the total plus length), or a
  stronger penalty, and check whether weights learned with archive winners
  carry over within a school.
- More winners from schools other than Carlmont would make the
  within-school check possible beyond one school.
