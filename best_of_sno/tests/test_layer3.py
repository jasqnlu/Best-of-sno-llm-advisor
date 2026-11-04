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
    assert out == {"rows": 3, "missing": 0, "stories_by_runs": {1: 3}, "path": out["path"]}
    rows = list(csv.DictReader(open(out["path"], encoding="utf-8")))
    assert [(r["id"], r["total"], r["long_enough"]) for r in rows] == [
        ("t1", "28", "1"), ("t2", "14", "0"), ("a2", "14", "1")]


def _scored(d, ids, v=3):
    with open(layer3.scores_file(d, "m"), "w", encoding="utf-8") as f:
        for i in ids:
            f.write(json.dumps({"id": i, "model": "m", "scores": _scores(v)}) + "\n")


def test_consistency_reports_exact_repeats(tmp_path):
    d = _setup(tmp_path)
    _scored(d, ["t1", "t2", "a2"])
    calls = []

    def fake(model, title, body):
        calls.append(title)
        return {"scores": _scores(3), "seconds": 0}

    out = layer3.consistency(d, "m", n=2, scorer=fake, log=lambda *_: None)
    assert len(calls) == 2
    assert out["compared"] == 2 and out["identical"] == 2 and out["differing"] == []
    with open(layer3.consistency_file(d, "m"), encoding="utf-8") as f:
        assert len(f.read().splitlines()) == 2


def test_consistency_flags_changed_scores_and_never_touches_main_file(tmp_path):
    d = _setup(tmp_path)
    _scored(d, ["t1", "t2", "a2"])
    before = open(layer3.scores_file(d, "m"), encoding="utf-8").read()

    def fake(model, title, body):
        s = _scores(3)
        if title == "T2":
            s["lede"]["score"] = 4
        return {"scores": s, "seconds": 0}

    out = layer3.consistency(d, "m", n=10, scorer=fake, log=lambda *_: None)
    assert out["compared"] == 3 and out["identical"] == 2
    assert out["differing"] == [{"id": "t2", "dimensions": ["lede"]}]
    assert open(layer3.scores_file(d, "m"), encoding="utf-8").read() == before


def test_consistency_counts_errors_separately(tmp_path):
    d = _setup(tmp_path)
    _scored(d, ["t1"])
    out = layer3.consistency(d, "m", n=5, scorer=lambda *a: {"error": "boom"},
                             log=lambda *_: None)
    assert out["compared"] == 0 and out["errors"] == 1


def test_second_run_scores_fresh_and_export_averages_runs(tmp_path):
    d = _setup(tmp_path)
    with open(scores_path(d, "m"), "w", encoding="utf-8") as f:   # trial = run 1 only
        f.write(json.dumps({"id": "t1", "model": "m", "scores": _scores(4)}) + "\n")
    layer3.score(d, "m", scorer=lambda *a: {"scores": _scores(2)}, log=lambda _: None)
    calls = []

    def fake(model, title, body):
        calls.append(title)
        return {"scores": _scores(3), "seconds": 1}

    res = layer3.score(d, "m", run=2, scorer=fake, log=lambda _: None)
    assert res["reused"] == 0 and calls == ["T1", "T2", "A2"]
    assert layer3.scores_file(d, "m", 2).endswith("layer3_scores_m_run2.jsonl")

    out = layer3.export(d, "m")
    assert out["stories_by_runs"] == {2: 3}
    rows = {r["id"]: r for r in csv.DictReader(open(out["path"], encoding="utf-8"))}
    assert rows["t1"]["lede"] == "3.5" and rows["t1"]["total"] == "24.5"
    assert rows["t2"]["lede"] == "2.5" and rows["t2"]["runs"] == "2"


def test_export_needs_run_one(tmp_path):
    d = _setup(tmp_path)
    layer3.score(d, "m", run=2, scorer=lambda *a: {"scores": _scores(3)}, log=lambda _: None)
    assert layer3.export(d, "m")["missing"] == 3
