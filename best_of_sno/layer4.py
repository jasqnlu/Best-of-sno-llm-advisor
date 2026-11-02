"""Layer 4: the chance bar. Turns the seven Layer 3 scores plus word count
into a chance of winning Best of SNO, for in-depth features.

    python -m best_of_sno.layer4 evaluate   # held-out checks, no files written
    python -m best_of_sno.layer4 fit        # -> data/layer4_model.json

Logistic regression, written out here because the model is tiny (8 inputs,
~700 stories) and not worth numpy/scikit-learn as dependencies.

- Inputs: the seven scores and log word count. ``source`` is never an
  input: every archive row is a winner, so it would be a free giveaway.
- Winners and non-winners are weighted to count equally, so the 518
  archive winners don't drown out the 155 non-winners.
- The percentage is then set to the real rate at the owner's schools: of
  the features they published in the window, ``BASE_RATE`` won. A story the
  model can't tell apart reads as that rate, not as 50%.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics

from .layer3_trial import auc
from .scorer import DIMENSION_KEYS

FEATURES = DIMENSION_KEYS + ["log_words"]
L2 = 1.0                 # ridge penalty on standardized coefficients
FOLDS, REPEATS, SEED = 5, 10, 20261101


def load_rows(data_dir: str) -> list[dict]:
    with open(os.path.join(data_dir, "data", "layer3_scores.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["y"] = int(r["label"] == "winner")
        r["log_words"] = math.log(max(int(r["word_count"]), 1))
        for k in DIMENSION_KEYS:
            r[k] = int(r[k])
    return rows


def base_rate(rows: list[dict]) -> float:
    """Share of the owner's schools' features that won (archive excluded)."""
    school = [r["y"] for r in rows if r["source"] == "training"]
    return sum(school) / len(school)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit(rows: list[dict], features: list[str] = FEATURES, *, l2: float = L2,
        target_rate: float | None = None) -> dict:
    """Class-balanced, L2-penalized logistic regression by Newton's method.
    Returns a plain-JSON model."""
    means = {f: statistics.mean(r[f] for r in rows) for f in features}
    sds = {f: statistics.pstdev([r[f] for r in rows]) or 1.0 for f in features}
    xs = [[1.0] + [(r[f] - means[f]) / sds[f] for f in features] for r in rows]
    ys = [r["y"] for r in rows]
    npos = sum(ys)
    nneg = len(ys) - npos
    w = [len(ys) / (2 * npos) if y else len(ys) / (2 * nneg) for y in ys]
    beta = [0.0] * (len(features) + 1)
    for _ in range(50):
        grad = [0.0] * len(beta)
        hess = [[0.0] * len(beta) for _ in beta]
        for x, y, wi in zip(xs, ys, w):
            p = _sigmoid(sum(b * v for b, v in zip(beta, x)))
            for i, xi in enumerate(x):
                grad[i] += wi * (y - p) * xi
                for j in range(i, len(x)):
                    hess[i][j] += wi * p * (1 - p) * xi * x[j]
        for i in range(1, len(beta)):          # intercept is not penalized
            grad[i] -= l2 * beta[i]
            hess[i][i] += l2
        for i in range(len(beta)):
            for j in range(i):
                hess[i][j] = hess[j][i]
        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    # Balanced weights make the fitted prior 50/50; shift to the real rate.
    rate = base_rate(rows) if target_rate is None else target_rate
    intercept = beta[0] + math.log(rate / (1 - rate))
    return {"features": features, "means": means, "sds": sds, "intercept": intercept,
            "coefs": dict(zip(features, beta[1:])), "base_rate": rate, "l2": l2}


def predict(model: dict, row: dict) -> float:
    z = model["intercept"] + sum(c * (row[f] - model["means"][f]) / model["sds"][f]
                                 for f, c in model["coefs"].items())
    return _sigmoid(z)


# The model is only a little better than length inside one school (held-out
# AUC 0.64 vs 0.62), so the chance bar shows a band, not a precise percent.
# Held out on the owner's schools, these bands won 2% / 31% / 54% of the time.
BANDS = ((0.20, "Low"), (0.40, "Medium"), (float("inf"), "High"))


def chance_band(p: float) -> str:
    return next(name for cut, name in BANDS if p < cut)


def _folds(rows: list[dict], k: int, rng: random.Random) -> list[list[int]]:
    """Stratified by label and source, so every fold has school winners,
    archive winners and non-winners."""
    folds: list[list[int]] = [[] for _ in range(k)]
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["y"], r["source"]), []).append(i)
    n = 0
    for idx in groups.values():
        rng.shuffle(idx)
        for i in idx:
            folds[n % k].append(i)
            n += 1
    return folds


def cross_validate(rows: list[dict], features: list[str], *, train_filter=None,
                   folds: int = FOLDS, repeats: int = REPEATS, seed: int = SEED) -> dict:
    """Held-out predictions averaged over repeats. Scored on school-site
    rows (the real use: a draft from one of the owner's schools) and on all
    rows. ``train_filter`` limits which rows the model learns from."""
    rng = random.Random(seed)
    rate = base_rate(rows)
    sums = [0.0] * len(rows)
    for _ in range(repeats):
        for test in _folds(rows, folds, rng):
            held = set(test)
            train = [r for i, r in enumerate(rows) if i not in held
                     and (train_filter is None or train_filter(r))]
            m = fit(train, features, target_rate=rate)
            for i in test:
                sums[i] += predict(m, rows[i])
    preds = [s / repeats for s in sums]
    school = [i for i, r in enumerate(rows) if r["source"] == "training"]
    sp = [preds[i] for i in school]
    sy = [rows[i]["y"] for i in school]
    return {
        "auc_school": auc([p for p, y in zip(sp, sy) if y], [p for p, y in zip(sp, sy) if not y]),
        "auc_within": within_school_auc([rows[i] for i in school], sp),
        "auc_all": auc([p for p, r in zip(preds, rows) if r["y"]],
                       [p for p, r in zip(preds, rows) if not r["y"]]),
        "brier_school": statistics.mean((p - y) ** 2 for p, y in zip(sp, sy)),
        "mean_pred_school": statistics.mean(sp),
        "actual_rate_school": statistics.mean(sy),
        "calibration": _bins(sp, sy),
        "bands": [(name, sum(1 for p in sp if chance_band(p) == name),
                   statistics.mean([y for p, y in zip(sp, sy) if chance_band(p) == name] or [float("nan")]))
                  for _, name in BANDS],
    }


def within_school_auc(rows: list[dict], preds: list[float], min_each: int = 5) -> float:
    """AUC computed inside each school, then averaged (weighted by pairs).
    Across schools, a model can score well just by learning which school
    wins most (Carlmont: 54 of 60 school-site feature winners); inside one
    school that shortcut is gone. Schools with fewer than ``min_each``
    winners or non-winners are skipped."""
    by: dict[str, tuple[list, list]] = {}
    for r, p in zip(rows, preds):
        by.setdefault(r["school"], ([], []))[0 if r["y"] else 1].append(p)
    num = den = 0.0
    for pos, neg in by.values():
        if len(pos) >= min_each and len(neg) >= min_each:
            pairs = len(pos) * len(neg)
            num += auc(pos, neg) * pairs
            den += pairs
    return num / den if den else float("nan")


def _bins(preds: list[float], ys: list[int], edges=(0.15, 0.3, 0.5)) -> list[tuple]:
    """(range, stories, average predicted, actual win rate) per band."""
    out, lo = [], 0.0
    for hi in list(edges) + [1.01]:
        pick = [(p, y) for p, y in zip(preds, ys) if lo <= p < hi]
        if pick:
            out.append((f"{lo:.0%}-{min(hi, 1):.0%}", len(pick),
                        statistics.mean(p for p, _ in pick), statistics.mean(y for _, y in pick)))
        lo = hi
    return out


def evaluate(data_dir: str) -> str:
    rows = load_rows(data_dir)
    school_only = lambda r: r["source"] == "training"
    runs = [
        ("scores + length", FEATURES, None),
        ("scores only", DIMENSION_KEYS, None),
        ("length only", ["log_words"], None),
        ("scores + length, school rows only", FEATURES, school_only),
    ]
    lines = [f"{len(rows)} stories; school-site win rate {base_rate(rows):.1%} "
             f"({FOLDS}-fold x {REPEATS} held-out checks)", "",
             f"{'model':36} {'AUC within':>10} {'AUC school':>10} {'AUC all':>8} {'Brier':>6} {'avg pred':>8}"]
    best = None
    for name, feats, filt in runs:
        res = cross_validate(rows, feats, train_filter=filt)
        best = best or res
        lines.append(f"{name:36} {res['auc_within']:10.2f} {res['auc_school']:10.2f} {res['auc_all']:8.2f} "
                     f"{res['brier_school']:6.3f} {res['mean_pred_school']:8.1%}")
    lines += ["", "calibration, scores + length, school-site stories (held out):",
              f"{'predicted':10} {'stories':>7} {'avg pred':>8} {'won':>6}"]
    lines += [f"{b:10} {n:7} {p:8.0%} {a:6.0%}" for b, n, p, a in best["calibration"]]
    lines += ["", "chance bar bands, school-site stories (held out):",
              f"{'band':10} {'stories':>7} {'won':>6}"]
    lines += [f"{b:10} {n:7} {a:6.0%}" for b, n, a in best["bands"]]
    m = fit(rows)
    lines += ["", "weights (per 1 standard deviation; bigger = more pull toward winning):"]
    lines += [f"  {f:13} {c:+.2f}" for f, c in sorted(m["coefs"].items(), key=lambda kv: -kv[1])]
    lines.append("")
    lines.append("AUC within: winners vs non-winners inside the same school (only "
                 "Carlmont has enough of both); the honest test of judging writing. ")
    lines.append("AUC school: held-out school-site winners vs non-winners (0.5 = coin flip). "
                 "Brier: average squared miss on the percentage (lower is better; "
                 f"always guessing {base_rate(rows):.0%} gives "
                 f"{base_rate(rows) * (1 - base_rate(rows)):.3f}).")
    return "\n".join(lines)


def save_model(data_dir: str) -> dict:
    rows = load_rows(data_dir)
    model = fit(rows)
    model["trained_on"] = len(rows)
    path = os.path.join(data_dir, "data", "layer4_model.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    return {"path": path, "stories": len(rows), "base_rate": round(model["base_rate"], 4)}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument("cmd", choices=["evaluate", "fit"])
    a = p.parse_args(argv)
    print(evaluate(a.data_dir) if a.cmd == "evaluate" else save_model(a.data_dir))


if __name__ == "__main__":
    main()
