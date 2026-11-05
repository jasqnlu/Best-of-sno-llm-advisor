# Advice model: QDoRA fine-tuned Gemma (design)

Date: 2026-11-03. Status: **approved by the owner 2026-11-04** (base model,
data handling, output format and inspiration stories decided; one question
still open, see the end). Background: the 2026-11-01 brainstorm
(`docs/layer3-brainstorm-context.md` on branch
`docs/layer3-brainstorm-context`, sections 5–8) and the Layer 3 design
(`2026-11-01-layer3-subscore-rubric-design.md`).

## What it does

Given one draft, the advice model writes a short, draft-specific critique
that a student writer can act on. It runs on the owner's PC through Ollama,
after the Layer 3 scorer and the Layer 4 chance bar:

```
draft ──▶ scorer (gemma4:12b, pinned) ──▶ 7 scores + evidence quotes ──▶ chance bar (Low/Medium/High)
   │                                              │                              │
   └──────────────────────────────┬───────────────┴──────────────────────────────┘
                                  ▼
                       advice model (fine-tuned Gemma) ──▶ advice
```

The decision to fine-tune Gemma, rather than call Claude for each draft,
is the owner's (2026-11-01, reversing 2026-10-29). The owner accepts the
advice may be weaker than Claude's. No API key is used: Claude takes part
only in one-off training steps, through Claude Code subagents.

## Output format

Plain text in three parts, in this order:

1. **Biggest fixes (up to 3).** Each names one rubric dimension, quotes the
   draft (under 25 words, word for word), says what is wrong with that
   passage and what to do instead. Ordered by the FIX ORDER the prompt
   gives (see "Fix order" below).
2. **What's working (1).** One strength, quoted, so the writer keeps it.
3. **Length (only if under 500 words).** The fixed line "Under 500 words:
   in-depth features that win usually run longer." Length is never advice
   beyond that line (Layer 3 rule).
4. **Stories to learn from (2–3).** Archive winners the writer can read as
   models. **Code adds this part, not the model** (see below), so every
   link is a real winner.

The owner approved this sample (2026-11-04; made-up draft, ~430 words,
chance band Medium):

```
BIGGEST FIXES
1. Lede (2/5) — "On Friday, the district announced that custodian Ray Ortiz
   will retire after 31 years." This opens on news a district email already
   gave everyone. Open on a scene only you saw — Ortiz on his nightly round —
   and bring in the retirement by the third paragraph.
2. Sourcing (2/5) — "Many students say he is the heart of the school."
   "Many students" is no one. Name two students and a coworker from his
   shift, and quote each on one specific moment, not general praise.
3. Depth (3/5) — "He has seen a lot of changes over the years." Name them:
   ask about the year the gym flooded or the 1994 remodel, and give one
   concrete before-and-after.

WHAT'S WORKING
Craft — "He still keys the boiler room door left-handed, the way his
father taught him." A detail that shows who he is. Keep it, and find more.

LENGTH
Under 500 words: in-depth features that win usually run longer.

STORIES TO LEARN FROM
• "[Archive winner title]" — [School], [Month Year] — bestofsno.com/…
  Read for the lede (5/5): two paragraphs of scene before any news.
• "[Archive winner title]" — [School], [Month Year] — bestofsno.com/…
  Read for sourcing (5/5): six named voices, each tied to a moment.
```

### Choosing the stories to learn from

Picked by code after the model writes parts 1–3, so the fine-tuned model
never writes a URL (a 12B model can invent links):

- **Pool:** archive winners in the 733 scored features, minus the 60
  held-out stories and the draft itself.
- **Topic match:** embed each story's title and opening (first ~300 words)
  with a local Ollama embedding model (e.g. `nomic-embed-text`); rank the
  pool by cosine similarity to the draft. Embeddings are cached in
  `best_of_sno/data/advice/` (git-ignored).
- **Fit to the fixes:** for each of the draft's top fixes, take the most
  similar winner that scored 5 on that dimension; skip repeats, stop at 3.
  If none scores 5, take the highest scorer among the 20 most similar.
- **"Read for" line:** filled from that winner's score and the rubric's
  description of that score, not written freely, and never quoting the
  winner.
- Stories under 150 words (stubs) are never picked, and never used as
  training examples.
- Titles, schools, dates and URLs come from `archive.csv` as published on
  bestofsno.com.

The model never states the chance as a percentage (Layer 4 decision) and
never claims a reason a story would win that it can't point to in the
scores.

### Fix order

Built 2026-11-04 (`advice.fix_order`). The first design ranked fixes by
Layer 4 weight × gap to 5. On the real data that breaks: sourcing and
depth have weights of about zero or below, so they would never be fixed
even at 1/5, and a weight boost of ×0.5–×1.5 still put craft first for 632
of 733 stories. The order is now **the gap to 5, nudged by the weight**
(×0.75 for a weight at or below zero, up to ×1.25 for the largest). First
fixes across the 733: craft 309, lede 280, focus 47, significance 40,
depth 28, quotes 14, sourcing 9. Ties go to the lower score, then rubric
order.

## Inputs (the prompt)

Pinned, like the scorer prompt, so training and use match:

- the draft's title and body;
- the seven scores, each with its evidence quote (only when the quote is
  really in the story: 11% of run-1 evidence isn't, e.g. copied anchor text);
- the chance band;
- word count and the 500-word check;
- the FIX ORDER: dimensions below 5, most important first.

Training examples are built from the final rubric's scores: focus-v2,
pinned 2026-11-04, two runs averaged (`layer3_scores.csv`).

## Training data

**Stories.** The 733 scored in-depth features (155 school non-winners,
60 school winners, 518 archive winners). Other story types are left out
for now because the chance bar covers features only.

**Held out for evaluation:** the 60 scorer-trial stories (30 winners,
30 length- and school-matched non-winners). They are never trained on.

**Round 0: imitation (supervised fine-tuning).** Claude subagents write
advice in the exact output format for training stories, 25 per subagent
batch. `export-examples` picks half non-winners and half winners (of the
winners, half from the school sites), seeded; the default is 100 stories,
to check format and quality before going to 300. Each reply is
checked by code before it is kept:

- every quote is in the draft (`scorer.evidence_found`);
- every named dimension exists and the fixes target dimensions scoring
  below 5;
- the format has the three parts, and nothing about length beyond the
  fixed line.

**Rounds 1–2: Gemma writes, Claude grades.** The round-0 model writes four
versions of advice for each training story (temperature 0.7). Claude
subagents grade each version against the checklist below, without knowing
which version is which. Versions that pass the code checks and score at
least 4 of 5 on the checklist become the next round's training set; the
best per story is kept. Stop after two rounds or when the held-out
checklist score stops rising.

**Checklist (each yes/no):**
1. Specific to this draft: would it be wrong for a different story?
2. Points at the weakest high-weight dimensions.
3. A writer would know exactly what to change.
4. Quotes are used to show the problem, not decoration.
5. No generic tips ("show, don't tell", "add more quotes") without a
   specific place in the draft.

## Fine-tuning setup

- **Method:** QDoRA (4-bit base, DoRA adapters) on Google Colab, with
  Hugging Face `transformers`, `peft` (`use_dora=True`) and
  `bitsandbytes`. Rank 16, alpha 32, all attention and MLP projections,
  2 epochs, learning rate 1e-4, loss on the advice tokens only.
- **Base model: Gemma 12B (decided 2026-11-04).** It matches the scorer and
  is the stronger writer. Stories run up to ~6.7k prompt tokens, so 12B
  training needs a Colab GPU with about 24 GB or more (L4 or A100), which
  needs Colab Pro. The owner will buy Colab Pro when training starts; until
  then, all the steps before training (examples, code checks, export) can be
  built and tested on the PC. The small-model trial run is skipped.
- **Back to the PC:** merge the adapter into the base model, convert to
  GGUF, quantize to `Q4_K_M` (the same as the untrained baseline, so
  before/after comparisons are fair), and load it in Ollama under a new
  name (e.g. `sno-advisor:r0`).

## Evaluation

On the 60 held-out stories, compare untrained Gemma, each fine-tuned round
and Claude (subagents), all given the same prompt:

| Measure | How |
|---|---|
| Code checks pass rate | quotes found, format, targets sub-5 dimensions |
| Checklist score (0–5) | Claude subagents, blind to which model wrote it |
| Owner review | the owner ranks 10 stories' advice from three models, unlabeled |

A round ships only if it beats untrained Gemma on the checklist and the
owner prefers it on most of the 10.

## Code plan

- `best_of_sno/advice.py`: build the pinned prompt; `export-examples`
  (stories + scores → JSONL for subagents); `import` (validate subagent
  advice with the code checks); `export-train` (chat-format JSONL for
  Colab); `run MODEL` (advice for the held-out set through Ollama);
  `grade-batch` / `import-grades`; `compare`; `embed` (cache embeddings
  for the archive-winner pool) and `inspire` (append "Stories to learn
  from" to a piece of advice).
- `notebooks/qdora_advice.ipynb`: the Colab training notebook. It reads the
  training JSONL from the owner's Google Drive; no story text is committed.
- Everything with story text stays in `best_of_sno/data/advice/`
  (git-ignored).

## Data handling (decided 2026-11-04)

Training files contain full story text. The owner approved uploading them
to their private Google Drive for Colab. Size: the 733 scored features are
about 913,000 words (~5.6 MB of text, ~1.2M tokens; median 1,112 words,
longest 4,603), so the training JSONL for all 673 non-held-out stories is
under 10 MB. Nothing with story text is committed.

## Decisions (2026-11-04)

1. Base model: straight to Gemma 12B; Colab Pro bought when training starts.
2. Uploading training text to the owner's Google Drive for Colab: approved.
3. Output format: the sample above is approved, with a fourth part, "Stories
   to learn from", picked by code.

## Still open

1. About 300 Claude-written examples for round 0 (roughly 12 subagent
   batches): enough, or start with 100?
