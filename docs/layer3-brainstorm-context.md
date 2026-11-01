# Layer 3 brainstorm: context for the next session (2026-11-01)

Read this first if you are picking up the Layer 3 design, especially on the
owner's PC. It records everything decided in the 2026-11-01 brainstorm, what
is still a proposal, and what is still open. Background, in order:
`docs/project-context.md` (goals, architecture, Layers 1–2), then
`docs/session-handoff.md` (state on 2026-11-01). Where this file disagrees
with either, this file wins.

**Status: brainstorm in progress. Nothing for Layer 3 is built. No written
design yet.** The next step is to finish the open questions below, then
write the design to
`docs/superpowers/specs/2026-11-01-layer3-subscore-rubric-design.md`.

Labels used below:
- **[owner]**: the owner said or decided it. Don't re-ask.
- **[proposal]**: Claude proposed it; the owner hasn't objected but hasn't
  explicitly approved it. Confirm when writing the design.
- **[open]**: not decided.

---

## 1. Where the project stands

- `main` includes PR #11 (page saving, `--reparse`). 201 tests on `main`.
- **PR #12 is open** (`feat/training-data-prep`): `best_of_sno/prep.py`
  builds `best_of_sno/data/training.csv` from `layer2.csv`. 215 tests.
  - Strips "Story continues below advertisement", the leading "Name · "
    photo credit on Carlmont long-form stories (a source tell: 13/81
    winners vs 14/1,710 non-winners had it), and escaped HTML.
  - Drops 146 rows under 20 words (crosswords, trivia, sudoku, galleries,
    issue PDFs). Photo essays (20–80 words) stay.
  - Writes through the formula-guarded CSV writer.
  - Result: **81 winners + 1,564 non-winners.** `uncertain.csv` is never
    read (held out).
- Run it: `python -m best_of_sno.prep`.

## 2. What Layer 3 is

Layer 3 turns each story into about seven named 1–5 scores. They feed:
- **Layer 4**: logistic regression → the chance bar (0–100%). Because the
  bar is built from named scores, it explains itself ("lede 2/5 is what's
  dragging you down").
- **The advice model** (section 7), which must ground its advice in the
  scores and the chance bar.

**A 1–5 score is not a chance of winning.** It rates one quality, like a
rubric grade. Layer 4 learns from the data how much each quality matters for
winning. [owner asked; this is the agreed meaning]

## 3. Data finding that shapes the design

Measured on `training.csv`, 2026-11-01:

| | Winners (81) | Non-winners (1,564) |
|---|---|---|
| Words p10 / median / p90 | 815 / 1,331 / 2,471 | 283 / 701 / 1,228 |
| Top categories | Features 58, News 9, Editorial 3, Sports 2 | Sports 176, News 158, Class of 2026 135, Features 113, A&E 83, Opinion 82, Briefs 79 … |

Best of SNO archive winners (1,862) by category: Features 624, News 283,
Sports 210, Arts & Entertainment 181, College Reporting 174, Multimedia 133,
Opinions 128, Photo 35 …

**Risk:** a rubric could separate winners from non-winners for the wrong
reason (long feature vs. short sports brief) instead of writing quality.
Every design choice below guards against that.

## 4. Decisions

### Dimensions [owner gave 1–4; 5–7 are proposal]
Owner's words for what makes winners different: "strong sources, great
quotes, good ledes, stays committed on the topic." Owner on sources: means
people with a direct stake in the story, more than many sources [owner
confirmed].

1. **Lede:** the opening pulls you in and points at the stakes.
2. **Sourcing:** people with a direct stake; a range of viewpoints; named
   over anonymous.
3. **Quotes:** reveal feeling or insight the writer couldn't paraphrase,
   not logistics.
4. **Focus:** stays on one angle; every section serves it.
5. **Reporting depth** [proposal]: facts, data, documents, scenes beyond
   interviews.
6. **Significance** [proposal]: why readers should care; stakes beyond the
   school.
7. **Craft** [proposal]: clear sentences, flow between sections, a real
   ending.

- Each score is 1–5 with an anchored description per level, and the scorer
  returns a short evidence quote from the story per score [proposal]. The
  evidence quote is reused by the advice model.
- **Story length is not a score.** Layer 4 accounts for it separately so
  "write more" never becomes the advice [proposal].

Draft anchor table for lede [proposal; owner asked how scoring works and
didn't object]. The other six tables are still to write [open].

| Score | Lede |
|---|---|
| 1 | Generic opening ("On Tuesday, the school board met…"); nothing to pull you in. |
| 2 | States the topic but no hook or stakes. |
| 3 | A decent hook, but the stakes come a few paragraphs later. |
| 4 | Strong hook; stakes clear in the first paragraph or two. |
| 5 | A specific detail or scene you'd remember that leads straight into why the story matters. |

### Scope [owner]
- **Option B for now:** the chance bar is trained and shown for **in-depth
  features only**: winning features vs. non-winning features, plus feature
  winners from the archive (624). This also removes the "feature vs. brief"
  shortcut.
- **Everyone on the staff uses the tool, whatever they write** [owner].
  So: every story type gets the seven scores and advice; only features get a
  percentage. Other types show "chance bar not available for this story type
  yet" instead of a made-up number [proposal, fits the project anti-goal of
  "a confident number with nothing behind it"].
- **The scorer also tags story type** (feature, news, sports, opinion,
  profile, review, other) in the same pass, because site categories are
  messy and drafts have none [proposal].
- Later: add a chance bar per story type as archive winners come in
  (Option A, one type at a time).

### Validation [owner agreed to hand-score; rest is proposal]
- **Owner hand-scores 5 stories** on all seven dimensions (owner chose 5
  over 20). That's a sanity check for badly worded tables, not a statistical
  test. Mix winners, non-winners and borderline cases; hide which is which.
  Build a simple page showing one story with the tables beside it, saving
  scores as the owner goes.
- **Main test:** for each dimension, do winners score higher than
  non-winners among features? A dimension that doesn't separate them gets
  reworded or dropped before Layer 4.
- **Consistency:** score about 30 stories twice; the same story should get
  the same scores.
- **Length check:** scores must not just track word count.

### Scorer trial [decided: run all three; owner left the call to Claude]
Run the same **60 stories** through each candidate scorer with the same
rubric, then pick the one that best separates winners and best matches the
owner's 5 hand-scored stories. Why all three: it costs one extra model on
the PC; Claude gives the quality bar; the two Gemma sizes show whether 12B
judges writing noticeably better, which also informs which size to
fine-tune for the advice model.
- Claude via the API.
- Gemma, untrained (as Google publishes it, instruction-tuned), small size.
- Gemma 12B, untrained.

Training stories and real drafts **must be scored by the same pinned
setup** (same model, prompt, settings, randomness off), or the chance bar
drifts. That's why final scoring isn't done by Claude Code subagents.
Subagents are fine for a quick rubric trial. Owner asked about subagents;
this was the answer.

## 5. Reversal of the 2026-10-29 decision [owner, 2026-11-01]

`project-context.md` says the QDoRA fine-tuned advice model was cut on
2026-10-29 ("distilling Claude's critiques gives a weaker copy of Claude").
**The owner reversed this on 2026-11-01.** Gemma will be **QDoRA
fine-tuned to write the advice**, using the scores and chance bar from the
stats pipeline. The owner accepts that it may be weaker than Claude's
advice. Update `project-context.md` to match when the Layer 3 design is
written.

## 6. Project order [proposal]

These are separate projects; each needs the one before:
1. **Layer 3 (now):** write the seven tables; scorer trial on 60 stories;
   owner's 5 hand-scored stories.
2. Score all feature stories with the winning scorer.
3. **Layer 4:** fit the chance bar on those scores.
4. **Gemma advice model:** build training examples (story → seven scores →
   chance bar → good advice), then QDoRA fine-tune. Brainstorm this
   separately.

Fine-tuning can't usefully start before 1–3: the training examples need the
scores and chance bar. Untrained Gemma in the Layer 3 trial also gives a
before-training baseline.

## 7. Advice model: training approaches discussed [owner raised both]

1. **Copy Claude (supervised fine-tuning):** Claude writes grounded advice
   for a few hundred stories; Gemma learns to imitate it. Simple; can at
   best match those examples.
2. **Gemma writes, Claude grades:** Gemma writes several versions of advice
   per story; Claude grades each against a checklist (specific to this
   draft? points at the weakest scores? would a writer know what to
   change?); fine-tune on the best-graded; repeat. Not full RL, but Gemma
   improves from feedback instead of only imitating.

Recommended [proposal]: 1 first (teaches the format), then rounds of 2.
Owner's idea of Gemma "deducing why a piece won by itself" needs grounding:
Gemma can't check its own reasons, so advice must point at the scores that
Layer 4 shows actually separate winners.

## 8. Hardware

**Mac** (where 11-01 work happened): Apple M5, 16 GB RAM, 443 GB free.
Ollama has `gemma4:latest` (8.1B parameters, the "effective 4B" small
build, nvfp4, 9.5 GB, default temperature 1) and `qwen3:14b`.

**Who does what [owner, 2026-11-01]:**
- **PC runs the models:** the Layer 3 scorer trial, scoring all feature
  stories, and running the fine-tuned advice model afterwards.
- **Google Colab does the fine-tuning** (QDoRA). The fine-tuned weights
  come back to the PC to run.

**PC:** RTX 2060 Super, 32 GB RAM. Notes to verify on the machine, not
measured:
- The 2060 Super has **8 GB of VRAM**. Gemma 12B at 4-bit is roughly 7–8 GB
  of weights plus working memory, so Ollama may split it between GPU and
  system RAM. It should run, but slower; scoring ~800 feature stories may
  take many hours, so time a few stories first. Small Gemma fits on the GPU.
- **Set temperature 0 for scoring** (Ollama default is 1).
- **Install both Gemma sizes [owner asked; yes]:** `ollama pull gemma4:e4b`
  and `ollama pull gemma4:12b` (tags checked on ollama.com 2026-11-01; the
  library also lists `-it-qat` and `-it-q8_0` variants). After pulling,
  `ollama show <tag>` and record the quantization of each. **Both trial
  models should use the same kind of 4-bit quantization**, so a gap between
  them is about size, not compression. Don't copy the Mac's
  `gemma4:latest`: it is nvfp4, a format built for newer NVIDIA cards than
  the 2060 Super.
- Running the fine-tuned model: export the Colab adapter merged into the
  base model and converted to a format Ollama loads (GGUF), and quantize it
  the same way as the untrained baseline so before/after comparisons are
  fair.

## 9. Setting up the PC

1. Clone the repo and check out the right branch (PR #12's
   `feat/training-data-prep` until it merges, then `main`).
2. **Data is gitignored and must never be committed** (story text). Copy
   the whole data folder from the Mac by hand (about 30 MB) with a USB
   drive or private local transfer, not a public service. On the Mac it is
   `/Users/jasonlu/Desktop/Best-of-sno-scraper/Best-of-sno-llm-advisor/best_of_sno/data/`;
   put it at `best_of_sno/data/` inside the PC's clone. What's in it:
   - `training.csv` (8.6 MB): cleaned winners + non-winners. **Layer 3 needs this.**
   - `archive.csv` (12 MB): 1,862 Best of SNO winners. **Needed** (archive
     feature winners, retrieval for advice).
   - `layer2.csv` (8.7 MB): raw crawl; `training.csv` is rebuilt from it.
   - `uncertain.csv`, `new.csv`, and the `*_state.json` files: small; copy
     them so the scrapers can resume if ever run from the PC.
   - `pages/`: empty for now; skip it.
3. Python venv + `pip install -r best_of_sno/requirements.txt`; run the
   tests.
4. Install Ollama; pull both Gemma sizes (section 8). Fine-tuning happens
   on Colab, not here.

## 10. Open questions (ask in this order)

1. **API key / budget for Claude** (the trial's Claude scorer, later the
   grading of Gemma's advice). Asked; the owner moved to the Gemma
   discussion before answering.
2. **How staff use the tool:** each writer pastes a draft into a page, or
   drafts go through the owner? (Asked; not answered.) This decides whether
   the final tool must run without the owner's machine.
3. Approve or change dimensions 5–7 and the "length is not a score" rule.
4. The other six anchor tables.

## 11. Owner preferences (from handoff, still in force)

- No Claude attribution anywhere: commit as `jasqnlu`, no `Co-Authored-By`
  trailer, no "Generated with Claude Code" PR footer.
- Plain-language updates; short approvals ("yeah", "yes sounds good").
- New work on a feature branch off `main`, merged through a PR.
- Never commit story text.
