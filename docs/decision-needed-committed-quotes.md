# Decision needed: story quotes pushed to a public branch

Date: 2026-11-03. Needs a reply from the owner.

## What happened

While committing the Focus rewording to PR #17
(`feat/focus-v2-trial-and-averaging`), Claude used `git add -A`, which also
picked up three files that should never have been committed:

| File | What's in it |
|---|---|
| `best_of_sno/data/layer3_scores_gemma4_12b.focus-v1.jsonl.bak` | Old (Focus v1) scores for the 733 features. Each story has 7 short evidence quotes (under 25 words each) copied from the story. |
| `best_of_sno/data/layer3_consistency_gemma4_12b.focus-v1.jsonl.bak` | The same kind of record for the 30 consistency-check stories. |
| `best_of_sno/logs/gpu-temps-2026-11-03.csv` | GPU temperature log. Harmless. |

No full stories are in them, but the quotes are other students' copyrighted
writing, and the repository is **public**. This breaks the rule "never
commit anything in `best_of_sno/data/`".

## What's already done

- A follow-up commit on the branch deletes the files and adds `*.bak` in
  `data/` and `*.csv` in `logs/` to `.gitignore`. The branch's current
  files are clean.
- The files are **still visible in one commit, `6890183`**, in the
  branch's history and in PR #17's commit list.
- Rewriting that commit needs a force-push. The permission check blocked
  Claude from doing that without your say-so.

## Options

**A. Squash-merge #17 (simple).** Use "Squash and merge" on PR #17, so
`main` gets one clean commit without the files. The old commit stays
reachable on GitHub through PR #17's history.

**B. Rewrite the branch (thorough, recommended).**
1. Claude rebuilds the branch without commit `6890183` and force-pushes it.
2. Claude closes #17 and opens a fresh PR with the same changes, so no PR
   lists the old commit.
3. Optional: ask GitHub Support to purge cached views of the old commit.
   GitHub can keep unreachable commits viewable by their ID until it
   cleans them up. Their form is "Remove sensitive data" under
   support.github.com.

**C. Leave it.** The quotes are short, scattered fragments, but they stay
public.

## Reply with

- "go ahead with the force push" → option B, or
- "squash merge" → option A (you merge #17 with Squash and merge).

Merge or close this PR after deciding; the note isn't needed on `main`
long term.
