"""Layer 3 scorer trial: story pick, resumable runs, Claude import, report."""

import csv
import json
import os

from best_of_sno import layer3_trial as t
from best_of_sno.scorer import DIMENSION_KEYS


def _row(i, label, wc, school="A", cat="Features"):
    return {"id": f"id{i}", "label": label, "word_count": str(wc), "school": school,
            "categories": cat, "title": f"T{i}", "body": f"story {i} body text"}


def _scores(v, story_type="feature"):
    s = {k: {"score": v, "evidence": "story"} for k in DIMENSION_KEYS}
    s["story_type"] = story_type
    return s


def test_pick_pairs_each_winner_with_a_close_length_non_winner():
    rows = [_row(1, "winner", 1000), _row(2, "winner", 2000),
            _row(3, "non_winner", 990), _row(4, "non_winner", 2100),
            _row(5, "non_winner", 300), _row(6, "winner", 900, cat="News")]
    picked = t.pick_trial(rows, n=5)
    assert [r["id"] for r in picked] == ["id2", "id4", "id1", "id3"]


def test_pick_prefers_the_same_school_within_25_percent():
    rows = [_row(1, "winner", 1000, school="A"),
            _row(2, "non_winner", 1000, school="B"),
            _row(3, "non_winner", 1200, school="A")]
    assert t.pick_trial(rows, n=1)[1]["id"] == "id3"


def test_handscore_mixes_winners_and_non_winners():
    trial = [_row(i, "winner" if i % 2 else "non_winner", 1000) for i in range(10)]
    ids = t.pick_handscore(trial, n=5)
    labels = [r["label"] for r in trial if r["id"] in ids]
    assert len(ids) == 5 and labels.count("winner") == 3


def _setup(tmp_path, rows):
    d = tmp_path / "data" / "layer3_trial"
    d.mkdir(parents=True)
    with open(d / "stories.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=t.STORY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return d


def test_run_scores_each_story_once_and_resumes(tmp_path):
    _setup(tmp_path, [_row(1, "winner", 1000), _row(2, "non_winner", 1000)])
    calls = []

    def scorer(model, title, body):
        calls.append(title)
        return {"scores": _scores(3), "seconds": 1.0}

    assert t.run(str(tmp_path), "m:x", scorer=scorer, log=lambda s: None)["scored"] == 2
    assert t.run(str(tmp_path), "m:x", scorer=scorer, log=lambda s: None)["skipped"] == 2
    assert calls == ["T1", "T2"]
    assert os.path.exists(t.scores_path(str(tmp_path), "m:x"))


def test_run_retries_stories_that_errored(tmp_path):
    _setup(tmp_path, [_row(1, "winner", 1000)])
    t.run(str(tmp_path), "m", scorer=lambda *a: {"error": "bad"}, log=lambda s: None)
    out = t.run(str(tmp_path), "m", scorer=lambda *a: {"scores": _scores(2)}, log=lambda s: None)
    assert out["scored"] == 1
    assert t.load_scores(t.scores_path(str(tmp_path), "m"))["id1"]["scores"]["lede"]["score"] == 2


def test_import_claude_validates_and_reports_problems(tmp_path):
    d = _setup(tmp_path, [_row(1, "winner", 1000), _row(2, "non_winner", 1000), _row(3, "winner", 900)])
    (d / "claude").mkdir()
    good = json.dumps({"id": "id1", "reply": _scores(4)})
    bad = json.dumps({"id": "id2", "reply": {"lede": {"score": 9}}})
    stranger = json.dumps({"id": "nope", "reply": _scores(4)})
    (d / "claude" / "out_1.jsonl").write_text("\n".join([good, bad, stranger, "{oops"]) + "\n", encoding="utf-8")
    out = t.import_claude(str(tmp_path))
    assert out["imported"] == 1
    assert out["missing"] == ["id2", "id3"]
    assert len(out["problems"]) == 3


def test_auc_and_spearman():
    assert t.auc([3, 4], [1, 2]) == 1.0
    assert t.auc([2], [2]) == 0.5
    assert abs(t.spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9


def test_compare_reports_separation_and_claude_agreement(tmp_path):
    _setup(tmp_path, [_row(1, "winner", 1000), _row(2, "non_winner", 1000),
                      _row(3, "winner", 1200), _row(4, "non_winner", 800)])
    for name, vals in [("claude", {"id1": 5, "id2": 2, "id3": 4, "id4": 1}),
                       ("m", {"id1": 4, "id2": 2, "id3": 4, "id4": 3})]:
        with open(t.scores_path(str(tmp_path), name), "w", encoding="utf-8") as f:
            for i, v in vals.items():
                f.write(json.dumps({"id": i, "scores": _scores(v), "seconds": 2}) + "\n")
    report = t.compare(str(tmp_path))
    assert "=== claude: 4 scored" in report and "=== m: 4 scored" in report
    assert "vs claude" in report
    claude_lede = next(line for line in report.splitlines() if line.startswith("lede"))
    assert " 1.00 " in claude_lede      # Claude's AUC: winners always higher


def _hand_setup(tmp_path):
    rows = [_row(1, "winner", 800), _row(2, "non_winner", 800, school="B")]
    rows[0]["body"] = "A tale with </script> inside"
    _setup(tmp_path, rows)
    (tmp_path / "data" / "layer3_trial" / "handscore_ids.txt").write_text("id1\nid2\n", encoding="utf-8")
    return tmp_path


def test_handscore_page_hides_labels_and_escapes_script_tags(tmp_path):
    path = t.handscore_page(str(_hand_setup(tmp_path)))
    html = open(path, encoding="utf-8").read()
    assert "T1" in html and "T2" in html
    assert "non_winner" not in html and '"winner"' not in html
    assert "</script> inside" not in html          # would end the page's script early
    assert "__STORIES__" not in html and "__DIMS__" not in html


def test_import_owner_validates_and_compare_reports_agreement(tmp_path):
    d = str(_hand_setup(tmp_path))
    src = tmp_path / "handscores.jsonl"
    bad = _scores(3)
    bad["lede"]["score"] = 9
    src.write_text("\n".join(json.dumps(x) for x in [
        {"id": "id1", "reply": _scores(4)},
        {"id": "id2", "reply": bad},
        {"id": "id9", "reply": _scores(3)},
    ]) + "\n", encoding="utf-8")
    res = t.import_owner(d, str(src))
    assert res["imported"] == 1 and res["missing"] == ["id2"] and len(res["problems"]) == 2

    with open(t.scores_path(d, "gemma"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "id1", "model": "gemma", "scores": _scores(5)}) + "\n")
    report = t.compare(d)
    assert "agreement with your hand scores" in report
    row = next(line for line in report.splitlines() if line.startswith("gemma ") and "%" in line)
    assert row.split()[1:] == ["1.00", "100%", "7.0"]


def test_run_with_a_variant_uses_its_rubric_and_own_file(tmp_path):
    _setup(tmp_path, [_row(1, "winner", 1000)])
    seen = []

    def scorer(model, title, body, variant=None):
        seen.append(variant)
        return {"scores": _scores(3)}

    t.run(str(tmp_path), "m", variant="focus-v1", scorer=scorer, log=lambda s: None)
    assert seen == ["focus-v1"]
    rec = t.load_scores(t.scores_path(str(tmp_path), "m+focus-v1"))["id1"]
    assert rec["variant"] == "focus-v1"
    assert not os.path.exists(t.scores_path(str(tmp_path), "m"))
