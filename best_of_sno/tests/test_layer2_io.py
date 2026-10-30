"""Tests for the wide-column writers + resume checkpoint (Layer 2, Task 5)."""

import csv

from best_of_sno.layer2 import (
    LAYER2_COLUMNS,
    UNCERTAIN_COLUMNS,
    append_rows,
    load_layer2_state,
    save_layer2_state,
)


def _rec(id_, columns, **kw):
    r = {c: "" for c in columns}
    r["id"] = id_
    r.update(kw)
    return r


def _rows(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_column_lists_extend_the_archive_schema():
    from best_of_sno.scraper import COLUMNS

    assert LAYER2_COLUMNS[:len(COLUMNS)] == COLUMNS
    assert LAYER2_COLUMNS[len(COLUMNS):] == ["label", "matched_id"]
    assert UNCERTAIN_COLUMNS[len(LAYER2_COLUMNS):] == [
        "reason", "candidate_title", "candidate_url"]


def test_append_writes_one_header_then_appends(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [_rec("a", LAYER2_COLUMNS, label="winner")], LAYER2_COLUMNS)
    append_rows(p, [_rec("b", LAYER2_COLUMNS, label="non_winner")], LAYER2_COLUMNS)
    rows = _rows(p)
    assert [r["id"] for r in rows] == ["a", "b"]
    assert [r["label"] for r in rows] == ["winner", "non_winner"]
    assert open(p, encoding="utf-8").read().count("id,url,title") == 1


def test_append_keeps_the_uncertain_columns(tmp_path):
    p = str(tmp_path / "uncertain.csv")
    append_rows(p, [_rec("u", UNCERTAIN_COLUMNS, label="uncertain",
                         reason="undated", candidate_title="T",
                         candidate_url="U")], UNCERTAIN_COLUMNS)
    r = _rows(p)[0]
    assert r["reason"] == "undated" and r["candidate_title"] == "T" and r["candidate_url"] == "U"


def test_append_is_a_noop_for_no_records(tmp_path):
    p = tmp_path / "layer2.csv"
    append_rows(str(p), [], LAYER2_COLUMNS)
    assert not p.exists()


def test_append_neutralizes_formula_injection(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [_rec("x", LAYER2_COLUMNS, title="=cmd()")], LAYER2_COLUMNS)
    assert _rows(p)[0]["title"].startswith("'")


def test_dialect_is_quote_minimal_like_the_archive(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [_rec("x", LAYER2_COLUMNS, title="A, B", summary="plain")],
                LAYER2_COLUMNS)
    text = open(p, encoding="utf-8").read()
    assert '"A, B"' in text  # a comma forces quoting
    assert '"plain"' not in text  # nothing else is quoted


def test_extra_keys_are_dropped_and_missing_keys_blank(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [{"id": "x", "bogus": "drop me"}], LAYER2_COLUMNS)
    r = _rows(p)[0]
    assert "bogus" not in r and r["title"] == "" and r["label"] == ""


def test_state_roundtrip_and_corrupt_fallback(tmp_path):
    sp = str(tmp_path / "layer2_state.json")
    assert load_layer2_state(sp) == set()
    save_layer2_state(sp, {"https://scotscoop.com/?p=1"})
    assert load_layer2_state(sp) == {"https://scotscoop.com/?p=1"}
    open(sp, "w").write("{bad json")
    assert load_layer2_state(sp) == set()
