# Consistency check: what to run on the PC

The Layer 3 scores (`data/layer3_scores_gemma4_12b.jsonl`) and the
`gemma4:12b` model live on the Windows PC, so this check runs there.

**What it tests:** the scorer is pinned (temperature 0, seed 0), so scoring
the same story twice should give exactly the same grades. If it doesn't, the
grades carry noise that Layer 4 learns from.

## Steps (PowerShell, in the repo folder)

```powershell
# 1. Get the branch
git fetch
git checkout chore/readme-layer4-and-consistency
git pull

# 2. Activate the venv
.venv\Scripts\Activate.ps1

# 3. Make sure Ollama is running and has the model
ollama list            # should show gemma4:12b; if not: ollama pull gemma4:12b

# 4. Run the check (about 15 minutes for 30 stories)
python -m best_of_sno.layer3 consistency gemma4:12b
```

It prints one line per story (`same` or `CHANGED lede, focus`), then a summary:

```
{'compared': 30, 'identical': 30, 'evidence_identical': 30, 'errors': 0, 'differing': []}
```

The re-scores go to `data/layer3_consistency_gemma4_12b.jsonl`. The main
scores file is not changed.

## Reading the result

| Result | Meaning | Next |
|---|---|---|
| `identical` = 30 | Scores are repeatable. | Record it in the Layer 3 design doc and move on. |
| A few differ by 1 point | Ollama isn't fully repeatable on this machine (GPU or batching). | Consider averaging two runs per story before Layer 4. |
| Many differ, or by 2+ | Setup drift (different model build, Ollama version, or options). | Check `ollama list` model ID and Ollama version before trusting the scores. |
| `errors` > 0 | Ollama call failed or the prompt hit the context limit. | Look at the printed error lines. |

## After the run

Paste the summary line back to Claude, or add it under "Open for Layer 4"
in `docs/superpowers/specs/2026-11-01-layer3-subscore-rubric-design.md`
and commit to this branch.
