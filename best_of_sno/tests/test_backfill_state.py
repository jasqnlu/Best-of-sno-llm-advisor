"""Tests for the archive writer + resumable checkpoint (Task 3)."""

import csv

from best_of_sno.backfill import append_rows, load_backfill_state, save_backfill_state
from best_of_sno.scraper import COLUMNS


def _rec(id_, **kw):
    r = {c: "" for c in COLUMNS}
    r["id"] = id_
    r.update(kw)
    return r


def _rows(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_append_writes_header_once_then_appends(tmp_path):
    p = str(tmp_path / "archive.csv")
    append_rows(p, [_rec("a", title="A")])
    append_rows(p, [_rec("b", title="B")])
    rows = _rows(p)
    assert [r["id"] for r in rows] == ["a", "b"]
    assert open(p, encoding="utf-8").read().count("id,url,title") == 1  # one header


def test_append_neutralizes_formula_injection(tmp_path):
    p = str(tmp_path / "archive.csv")
    append_rows(p, [_rec("x", title="=cmd()")])
    assert _rows(p)[0]["title"].startswith("'")


def test_state_roundtrip_and_corrupt_fallback(tmp_path):
    sp = str(tmp_path / "backfill_state.json")
    assert load_backfill_state(sp) == set()  # missing -> empty
    save_backfill_state(sp, {"a", "b"})
    assert load_backfill_state(sp) == {"a", "b"}
    open(sp, "w").write("{bad json")
    assert load_backfill_state(sp) == set()  # corrupt -> empty
