"""Layer 3 scorer trial: which scorer grades writing best?

    python -m best_of_sno.layer3_trial select      # pick the 60 stories
    python -m best_of_sno.layer3_trial run gemma4:e4b
    python -m best_of_sno.layer3_trial run gemma4:12b
    python -m best_of_sno.layer3_trial import-claude  # check + load subagent scores
    python -m best_of_sno.layer3_trial compare

Everything is written to best_of_sno/data/layer3_trial/ (git-ignored: it
holds story text). Each scorer writes ``scores_<name>.jsonl``, one line per
story; ``run`` skips stories already scored, so it can be stopped and resumed.
Claude's scores (from Claude Code subagents) go in ``scores_claude.jsonl``
in the same shape.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics

from .scorer import DIMENSION_KEYS, evidence_found, parse_scores, score_with_ollama

TRIAL_SIZE = 30          # winners; the same number of non-winners is matched
HANDSCORE_SIZE = 5
SEED = 20261101
STORY_COLUMNS = ["id", "label", "school", "word_count", "title", "body"]


def trial_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "data", "layer3_trial")


def _read_csv(path: str) -> list[dict]:
    csv.field_size_limit(2**31 - 1)
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _is_feature(row: dict) -> bool:
    return "feature" in row["categories"].lower()


def pick_trial(rows: list[dict], n: int = TRIAL_SIZE, seed: int = SEED) -> list[dict]:
    """``n`` winning features, each paired with the unused non-winning
    feature closest in length, preferring the same school when one is
    within 25% of the winner's length. Pairing on length and school keeps
    a scorer from looking good just by rewarding long stories or one
    school's house style."""
    rng = random.Random(seed)
    winners = [r for r in rows if r["label"] == "winner" and _is_feature(r)]
    pool = [r for r in rows if r["label"] == "non_winner" and _is_feature(r)]
    chosen = rng.sample(winners, min(n, len(winners)))
    picked = []
    for w in sorted(chosen, key=lambda r: -int(r["word_count"])):   # long first: fewer long non-winners
        wc = int(w["word_count"])
        gap = lambda r: abs(int(r["word_count"]) - wc)
        same = [r for r in pool if r["school"] == w["school"] and gap(r) <= 0.25 * wc]
        match = min(same or pool, key=gap)
        pool.remove(match)
        picked += [w, match]
    return picked


def pick_handscore(trial: list[dict], n: int = HANDSCORE_SIZE, seed: int = SEED) -> list[str]:
    """Ids for the owner to hand-score: a mix of winners and non-winners,
    shuffled so the order doesn't give the label away."""
    rng = random.Random(seed + 1)
    win = [r["id"] for r in trial if r["label"] == "winner"]
    non = [r["id"] for r in trial if r["label"] == "non_winner"]
    ids = rng.sample(win, (n + 1) // 2) + rng.sample(non, n // 2)
    rng.shuffle(ids)
    return ids


def select(data_dir: str) -> dict:
    rows = _read_csv(os.path.join(data_dir, "data", "training.csv"))
    trial = pick_trial(rows)
    out = trial_dir(data_dir)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "stories.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STORY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trial)
    hand = pick_handscore(trial)
    with open(os.path.join(out, "handscore_ids.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(hand) + "\n")
    return {"stories": len(trial), "handscore": len(hand)}


def scores_path(data_dir: str, name: str) -> str:
    safe = name.replace(":", "_").replace("/", "_")
    return os.path.join(trial_dir(data_dir), f"scores_{safe}.jsonl")


def load_scores(path: str) -> dict[str, dict]:
    """``{id: record}`` from a scores file; later lines win."""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def run(data_dir: str, model: str, *, scorer=score_with_ollama, log=print) -> dict:
    stories = _read_csv(os.path.join(trial_dir(data_dir), "stories.csv"))
    path = scores_path(data_dir, model)
    done = {i for i, r in load_scores(path).items() if "scores" in r}
    counts = {"scored": 0, "errors": 0, "skipped": len(done)}
    with open(path, "a", encoding="utf-8") as f:
        for n, s in enumerate(stories, start=1):
            if s["id"] in done:
                continue
            rec = {"id": s["id"], "model": model, **scorer(model, s["title"], s["body"])}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            counts["errors" if "error" in rec else "scored"] += 1
            log(f"[{n}/{len(stories)}] {model} {rec.get('seconds')}s "
                + (f"ERROR {rec['error']}" if "error" in rec else "ok"))
    return counts


def import_claude(data_dir: str) -> dict:
    """Validate the subagents' ``claude/out_*.jsonl`` files with the same
    parser the Gemma scorers go through and write ``scores_claude.jsonl``."""
    folder = os.path.join(trial_dir(data_dir), "claude")
    ids = {s["id"] for s in _read_csv(os.path.join(trial_dir(data_dir), "stories.csv"))}
    recs, problems = {}, []
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("out_") and name.endswith(".jsonl")):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if item.get("id") not in ids:
                        raise ValueError(f"unknown id {item.get('id')!r}")
                    scores = parse_scores(json.dumps(item["reply"]))
                except (ValueError, KeyError, TypeError) as e:
                    problems.append(f"{name}:{n}: {e}")
                    continue
                recs[item["id"]] = {"id": item["id"], "model": "claude", "scores": scores}
    with open(scores_path(data_dir, "claude"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs.values())
    return {"imported": len(recs), "missing": sorted(ids - set(recs)), "problems": problems}


def auc(pos: list[float], neg: list[float]) -> float:
    """Chance a random winner outscores a random non-winner (ties count
    half). 0.5 = no separation, 1.0 = perfect."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return float("nan")
    rx, ry = _ranks(xs), _ranks(ys)
    try:
        return statistics.correlation(rx, ry)
    except statistics.StatisticsError:      # one side is constant
        return float("nan")


def compare(data_dir: str) -> str:
    """A plain-text report: per scorer, how well each dimension separates
    winners, whether scores just track length, made-up evidence quotes, and
    agreement with Claude."""
    stories = {s["id"]: s for s in _read_csv(os.path.join(trial_dir(data_dir), "stories.csv"))}
    files = sorted(p for p in os.listdir(trial_dir(data_dir)) if p.startswith("scores_"))
    scorers = {p[len("scores_"):-len(".jsonl")]: load_scores(os.path.join(trial_dir(data_dir), p))
               for p in files}
    ref = scorers.get("claude", {})
    lines = []
    for name, recs in scorers.items():
        ok = {i: r["scores"] for i, r in recs.items() if "scores" in r and i in stories}
        if not ok:
            lines += [f"=== {name}: nothing scored yet", ""]
            continue
        errs = sum(1 for r in recs.values() if "error" in r and r["id"] not in ok)
        secs = [r["seconds"] for r in recs.values() if r.get("seconds")]
        lines.append(f"=== {name}: {len(ok)} scored, {errs} errors"
                     + (f", median {statistics.median(secs):.1f}s/story" if secs else ""))
        lines.append(f"{'dimension':13} {'win avg':>7} {'non avg':>7} {'AUC':>5} "
                     f"{'len rho':>7} {'quote ok':>8}" + (f" {'vs claude':>9} {'+/-1':>4}" if ref and name != "claude" else ""))
        totals_w, totals_n, quotes_ok, quotes_all = [], [], 0, 0
        for d in DIMENSION_KEYS + ["total"]:
            if d == "total":
                vals = {i: sum(s[k]["score"] for k in DIMENSION_KEYS) for i, s in ok.items()}
            else:
                vals = {i: s[d]["score"] for i, s in ok.items()}
                for i, s in ok.items():
                    quotes_all += 1
                    quotes_ok += evidence_found(s[d]["evidence"], stories[i]["body"])
            w = [v for i, v in vals.items() if stories[i]["label"] == "winner"]
            n = [v for i, v in vals.items() if stories[i]["label"] == "non_winner"]
            ids = list(vals)
            rho = spearman([vals[i] for i in ids], [int(stories[i]["word_count"]) for i in ids])
            q = "" if d == "total" else f"{sum(evidence_found(ok[i][d]['evidence'], stories[i]['body']) for i in ids)}/{len(ids)}"
            row = (f"{d:13} {statistics.mean(w) if w else float('nan'):7.2f} "
                   f"{statistics.mean(n) if n else float('nan'):7.2f} {auc(w, n):5.2f} {rho:7.2f} {q:>8}")
            if ref and name != "claude":
                shared = [i for i in ids if i in ref and "scores" in ref[i]]
                if d == "total":
                    rv = [sum(ref[i]["scores"][k]["score"] for k in DIMENSION_KEYS) for i in shared]
                    within = ""
                else:
                    rv = [ref[i]["scores"][d]["score"] for i in shared]
                    within = f"{sum(abs(vals[i] - r) <= 1 for i, r in zip(shared, rv)) / len(shared):4.0%}" if shared else ""
                row += f" {spearman([vals[i] for i in shared], rv):9.2f} {within:>4}"
            lines.append(row)
        if quotes_all:
            lines.append(f"evidence quotes found in the story: {quotes_ok}/{quotes_all} ({quotes_ok / quotes_all:.0%})")
        lines.append("")
    lines.append("AUC: chance a winner outscores a non-winner (0.5 = coin flip). "
                 "len rho: rank correlation with word count (want near 0). "
                 "vs claude: rank agreement with Claude; ±1: share within one point of Claude.")
    return "\n".join(lines)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select")
    r = sub.add_parser("run")
    r.add_argument("model")
    sub.add_parser("import-claude")
    sub.add_parser("compare")
    a = p.parse_args(argv)
    if a.cmd == "select":
        print(select(a.data_dir))
    elif a.cmd == "run":
        print(run(a.data_dir, a.model))
    elif a.cmd == "import-claude":
        print(import_claude(a.data_dir))
    else:
        print(compare(a.data_dir))


if __name__ == "__main__":
    main()
