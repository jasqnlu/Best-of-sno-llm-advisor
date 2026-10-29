"""Tests for atomic CSV write_new and rotate (Task 5)."""

import csv

from best_of_sno.scraper import COLUMNS, write_new, rotate


def _rec(id_):
    rec = {c: "" for c in COLUMNS}
    rec["id"] = id_
    return rec


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_write_new_roundtrips_special_chars(tmp_path):
    np = tmp_path / "new.csv"
    tricky = 'He said, "hi"\nnew line, with comma'
    rec = _rec("x1")
    rec["body"] = tricky
    write_new(str(np), [rec])
    rows = _read_rows(str(np))
    assert len(rows) == 1
    assert rows[0]["body"] == tricky


def test_write_new_empty_is_header_only(tmp_path):
    np = tmp_path / "new.csv"
    write_new(str(np), [])
    assert _read_rows(str(np)) == []
    header = np.read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == COLUMNS


def test_rotate_moves_rows_and_clears_new(tmp_path):
    np = tmp_path / "new.csv"
    op = tmp_path / "old.csv"
    write_new(str(np), [_rec("a"), _rec("b")])
    write_new(str(op), [])
    moved = rotate(str(np), str(op))
    assert moved == 2
    assert len(_read_rows(str(op))) == 2
    assert len(_read_rows(str(np))) == 0


def test_write_new_neutralizes_formula_injection(tmp_path):
    np = tmp_path / "new.csv"
    rec = _rec("x")
    rec["title"] = "=cmd|'/c calc'!A1"
    rec["body"] = "+SUM(1,2)"
    rec["author"] = "@evil"
    rec["summary"] = "-1+1"
    write_new(str(np), [rec])
    row = _read_rows(str(np))[0]
    assert row["title"].startswith("'")
    assert row["body"].startswith("'")
    assert row["author"].startswith("'")
    assert row["summary"].startswith("'")


def test_write_new_leaves_normal_values_untouched(tmp_path):
    np = tmp_path / "new.csv"
    rec = _rec("y")
    rec["title"] = "Normal Title"
    write_new(str(np), [rec])
    assert _read_rows(str(np))[0]["title"] == "Normal Title"


def test_rotate_appends_to_existing_old(tmp_path):
    np = tmp_path / "new.csv"
    op = tmp_path / "old.csv"
    write_new(str(op), [_rec("z")])
    write_new(str(np), [_rec("a"), _rec("b")])
    rotate(str(np), str(op))
    assert len(_read_rows(str(op))) == 3
