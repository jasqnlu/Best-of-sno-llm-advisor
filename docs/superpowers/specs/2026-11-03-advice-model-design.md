# Advice model: QDoRA fine-tuned Gemma (design)

Date: 2026-11-03. Status: **proposal, needs the owner's sign-off** on the
items marked [open]. Background: the 2026-11-01 brainstorm
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
   passage and what to do instead. Ordered by how much the fix should move
   the chance bar: Layer 4 weight × how far the score is below 5.
2. **What's working (1).** One strength, quoted, so the writer keeps it.
3. **Length (only if under 500 words).** The fixed line "Under 500 words:
   in-depth features that win usually run longer." Length is never advice
   beyond that line (Layer 3 rule).

The model never states the chance as a percentage (Layer 4 decision) and
never claims a reason a story would win that it can't point to in the
scores.

## Inputs (the prompt)

Pinned, like the scorer prompt, so training and use match:

- the draft's title and body;
- the seven scores, each with its evidence quote;
- the chance band;
- word count and the 500-word check;
- the Layer 4 weights, as a ranked list of which dimensions matter most.

Focus is currently being reworded (trial on 2026-11-03). Training examples
must be built from the **final** rubric's scores, so example building
waits until that settles.

## Training data

**Stories.** The 733 scored in-depth features (155 school non-winners,
60 school winners, 518 archive winners). Other story types are left out
for now because the chance bar covers features only.

**Held out for evaluation:** the 60 scorer-trial stories (30 winners,
30 length- and school-matched non-winners). They are never trained on.

**Round 0: imitation (supervised fine-tuning).** Claude subagents write
advice in the exact output format for about 300 training stories, mixing
winners and non-winners, 25 stories per subagent batch. Each reply is
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
- **Base model size [open]:** Gemma 12B matches the scorer and is the
  stronger writer, but stories run up to ~6.7k prompt tokens, so 12B
  training needs a Colab GPU with about 24 GB or more (L4 or A100: Colab
  Pro). The small Gemma (`e4b`) trains on the free T4. Proposal: run
  round 0 on the small model first (cheap check that the pipeline works
  end to end), then train 12B for real if Colab Pro is available.
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
  `grade-batch` / `import-grades`; `compare`.
- `notebooks/qdora_advice.ipynb`: the Colab training notebook. It reads the
  training JSONL from the owner's Google Drive; no story text is committed.
- Everything with story text stays in `best_of_sno/data/advice/`
  (git-ignored).

## Data handling [open]

Training files contain full story text. Uploading them to the owner's
private Google Drive for Colab keeps them off public services, but it is
still a copy outside the PC. The owner should confirm that's acceptable;
otherwise training has to happen on a local GPU (the 2060 Super's 8 GB is
too small for 12B QDoRA at this context length, and tight for the small
model).

## Open questions for the owner

1. Base model: small first then 12B (proposed), or straight to 12B? Is
   Colab Pro available?
2. Is uploading training text to your Google Drive for Colab OK?
3. Output format above: right length and parts? Should advice also cite a
   similar archive winner as an example (retrieval), as the 10-29 plan had?
4. About 300 Claude-written examples for round 0 (roughly 12 subagent
   batches): enough, or start with 100?
