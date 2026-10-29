"""Tests for state load/save with CSV rebuild (Task 4)."""

from best_of_sno.scraper import load_state, save_state


def _write_csv_with_ids(path, ids):
    lines = ["id,url,title"] + [f"{i},,," for i in ids]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_save_then_load_roundtrip(tmp_path):
    sp = tmp_path / "state.json"
    np = tmp_path / "new.csv"
    op = tmp_path / "old.csv"
    save_state(str(sp), {"last_run": "2026-10-28T08:00:00-07:00", "seen_ids": {"a", "b"}})
    loaded = load_state(str(sp), str(np), str(op))
    assert loaded["seen_ids"] == {"a", "b"}
    assert loaded["last_run"] == "2026-10-28T08:00:00-07:00"


def test_missing_state_rebuilds_from_csvs(tmp_path):
    sp = tmp_path / "state.json"  # does not exist
    np = tmp_path / "new.csv"
    op = tmp_path / "old.csv"
    _write_csv_with_ids(op, ["id-a", "id-b"])
    _write_csv_with_ids(np, ["id-c"])
    loaded = load_state(str(sp), str(np), str(op))
    assert loaded["seen_ids"] == {"id-a", "id-b", "id-c"}
    assert loaded["last_run"] is None


def test_corrupt_state_falls_back_to_csvs(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text("{bad json", encoding="utf-8")
    np = tmp_path / "new.csv"
    op = tmp_path / "old.csv"  # missing is fine
    _write_csv_with_ids(np, ["x"])
    loaded = load_state(str(sp), str(np), str(op))
    assert loaded["seen_ids"] == {"x"}


def test_save_is_atomic_no_tmp_left(tmp_path):
    sp = tmp_path / "state.json"
    save_state(str(sp), {"last_run": None, "seen_ids": set()})
    assert sp.exists()
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())
