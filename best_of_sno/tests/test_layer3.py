"""Layer 3 full scoring: which stories, reuse of trial scores, export."""

import csv
import json

from best_of_sno import layer3
from best_of_sno.layer3_trial import scores_path
from best_of_sno.scorer import DIMENSION_KEYS

LONG = " ".join(["word"] * 600)


def _scores(v):
    s = {k: {"score": v, "evidence": "word"} for k in DIMENSION_KEYS}
    s["story_type"] = "feature"
    return s


def _write(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _setup(tmp_path):
    d = tmp_path / "data"
    (d / "layer3_trial").mkdir(parents=True)
    tcols = ["id", "label", "school", "categories", "word_count", "title", "body", "matched_id"]
    _write(d / "training.csv", tcols, [
        {"id": "t1", "label": "winner", "school": "A", "categories": "Features", "word_count": 600,
         "title": "T1", "body": LONG, "matched_id": "a1"},
        {"id": "t2", "label": "non_winner", "school": "A", "categories": "Features", "word_count": 300,
         "title": "T2", "body": " ".join(["word"] * 300), "matched_id": ""},
        {"id": "t3", "label": "non_winner", "school": "A", "categories": "Sports", "word_count": 600,
         "title": "T3", "body": LONG, "matched_id": ""},
    ])
    acols = ["id", "school", "categories", "title", "body"]
    _write(d / "archive.csv", acols, [
        {"id": "a1", "school": "A", "categories": "Features", "title": "dup", "body": LONG},
        {"id": "a2", "school": "B", "categories": "Features", "title": "A2",
         "body": "Story continues below advertisement " + LONG},
        {"id": "a3", "school": "B", "categories": "Features", "title": "stub",
         "body": "View this story on the original site " * 4},
        {"id": "a4", "school": "B", "categories": "News", "title": "news", "body": LONG},
    ])
    return str(tmp_path)


def test_feature_set_skips_duplicates_stubs_and_other_types(tmp_path):
    stories = layer3.feature_set(_setup(tmp_path))
    assert [s["id"] for s in stories] == ["t1", "t2", "a2"]
    a2 = stories[-1]
    assert a2["label"] == "winner" and a2["source"] == "archive"
    assert "advertisement" not in a2["body"] and a2["word_count"] == 600


def test_score_reuses_trial_scores_resumes_and_exports(tmp_path):
    d = _setup(tmp_path)
    with open(scores_path(d, "m"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "t1", "model": "m", "scores": _scores(4)}) + "\n")
    calls = []

    def fake(model, title, body):
        calls.append(title)
        return {"scores": _scores(2), "seconds": 1}

    res = layer3.score(d, "m", scorer=fake, log=lambda _: None)
    assert calls == ["T2", "A2"]
    assert res["reused"] == 1 and res["scored"] == 2
    assert layer3.score(d, "m", scorer=fake, log=lambda _: None)["skipped"] == 3
    assert calls == ["T2", "A2"]

    out = layer3.export(d, "m")
    assert out == {"rows": 3, "missing": 0, "path": out["path"]}
    rows = list(csv.DictReader(open(out["path"], encoding="utf-8")))
    assert [(r["id"], r["total"], r["long_enough"]) for r in rows] == [
        ("t1", "28", "1"), ("t2", "14", "0"), ("a2", "14", "1")]
