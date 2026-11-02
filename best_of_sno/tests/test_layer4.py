"""Layer 4 chance bar: the fit, the base-rate shift, held-out checks."""

import math
import random

from best_of_sno import layer4 as L
from best_of_sno.scorer import DIMENSION_KEYS


def _rows(n=120, seed=1):
    """Winners score higher on lede; everything else is noise."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        y = int(i % 3 == 0)
        r = {k: rng.randint(2, 4) for k in DIMENSION_KEYS}
        r["lede"] = rng.randint(3, 5) if y else rng.randint(1, 3)
        r.update(y=y, log_words=math.log(rng.randint(500, 2000)),
                 source="training", school="A" if i % 2 else "B")
        rows.append(r)
    return rows


def test_solve_matches_a_known_system():
    assert [round(v, 6) for v in L._solve([[2, 1], [1, 3]], [3, 5])] == [0.8, 1.4]


def test_fit_finds_the_signal_and_sets_the_base_rate():
    rows = _rows()
    m = L.fit(rows)
    assert max(m["coefs"], key=m["coefs"].get) == "lede"
    assert abs(m["base_rate"] - 1 / 3) < 1e-9


def test_with_no_signal_every_story_reads_as_the_base_rate():
    rows = _rows()
    for r in rows:
        r["lede"] = 3                      # remove the only real signal
    m = L.fit(rows)
    preds = [L.predict(m, r) for r in rows]
    preds.sort()
    assert abs(preds[len(preds) // 2] - 1 / 3) < 0.05   # typical story: base rate, not 50%


def test_target_rate_only_moves_the_intercept():
    rows = _rows()
    a, b = L.fit(rows, target_rate=0.1), L.fit(rows, target_rate=0.5)
    assert a["coefs"] == b["coefs"]
    assert math.isclose(b["intercept"] - a["intercept"], math.log(0.5 / 0.5) - math.log(0.1 / 0.9))


def test_within_school_auc_ignores_the_school_shortcut():
    # School A: all winners predicted 0.9, B: all non-winners 0.1 -> across
    # schools that looks perfect; inside each school there's no signal.
    rows = ([{"school": "A", "y": 1}] * 5 + [{"school": "A", "y": 0}] * 5
            + [{"school": "B", "y": 0}] * 5 + [{"school": "B", "y": 1}] * 5)
    preds = [0.9] * 10 + [0.1] * 10
    assert L.within_school_auc(rows, preds) == 0.5
    assert L.within_school_auc(rows, preds, min_each=6) != L.within_school_auc(rows, preds)


def test_cross_validate_beats_chance_on_a_real_signal():
    res = L.cross_validate(_rows(), DIMENSION_KEYS, repeats=2)
    assert res["auc_school"] > 0.8 and res["auc_within"] > 0.8


def test_chance_band_cutoffs():
    assert [L.chance_band(p) for p in (0.0, 0.199, 0.2, 0.399, 0.4, 0.99)] == [
        "Low", "Low", "Medium", "Medium", "High", "High"]
