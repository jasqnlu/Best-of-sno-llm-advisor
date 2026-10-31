"""Tests for the site table + winners-corpus index (Layer 2, Task 4)."""

import csv

from best_of_sno.layer2 import SITES, load_winner_corpus, normalize_title
from best_of_sno.scraper import COLUMNS


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval="")
        w.writeheader()
        w.writerows(rows)


def _row(id_, title, school, **kw):
    r = {c: "" for c in COLUMNS}
    r.update(id=id_, title=title, school=school, published="2026-03-03",
             author="Ada Lee", url="https://bestofsno.com/1/a/b/", body="x " * 200)
    r.update(kw)
    return r


def test_sites_table_has_the_five_hosts_and_school_names():
    assert SITES == {
        "scotscoop.com": "Carlmont High School",
        "elestoque.org": "Monta Vista High School",
        "torreypinesfalconer.com": "Torrey Pines High School",
        "theburlingameb.org": "Burlingame High School",
        "harkeraquila.com": "The Harker School",
    }


def test_corpus_unions_all_three_winner_files(tmp_path):
    d = tmp_path / "data"
    _write(d / "archive.csv", [_row("A", "Archive Story", "Carlmont High School")])
    _write(d / "new.csv", [_row("N", "New Story", "Carlmont High School")])
    _write(d / "old.csv", [_row("O", "Old Story", "Monta Vista High School")])
    corpus = load_winner_corpus(str(tmp_path))
    assert {w["id"] for w in corpus["Carlmont High School"]} == {"A", "N"}
    assert {w["id"] for w in corpus["Monta Vista High School"]} == {"O"}


def test_a_winner_only_in_new_csv_is_in_the_corpus(tmp_path):
    # The poisoned-negative guard: run_backfill keeps daily-caught winners OUT
    # of archive.csv, so archive-only matching would mislabel them non_winner.
    d = tmp_path / "data"
    _write(d / "archive.csv", [_row("A", "Archive Story", "Carlmont High School")])
    _write(d / "new.csv", [_row("N", "Daily Caught Winner", "Carlmont High School")])
    titles = {w["norm_title"] for w in load_winner_corpus(str(tmp_path))["Carlmont High School"]}
    assert normalize_title("Daily Caught Winner") in titles


def test_missing_corpus_files_are_harmless(tmp_path):
    d = tmp_path / "data"
    _write(d / "archive.csv", [_row("A", "Only Archive", "Carlmont High School")])
    corpus = load_winner_corpus(str(tmp_path))  # no new.csv, no old.csv
    assert len(corpus["Carlmont High School"]) == 1


def test_corpus_is_empty_when_no_files_exist(tmp_path):
    assert load_winner_corpus(str(tmp_path)) == {}


def test_corpus_drops_body_and_precomputes_norm_title(tmp_path):
    _write(tmp_path / "data" / "archive.csv",
           [_row("A", "Don’t Look Away", "Carlmont High School")])
    w = load_winner_corpus(str(tmp_path))["Carlmont High School"][0]
    assert set(w) == {"id", "url", "title", "published", "author", "norm_title", "shingles"}
    assert w["norm_title"] == normalize_title("Don’t Look Away")


def test_corpus_excludes_schools_we_do_not_crawl(tmp_path):
    _write(tmp_path / "data" / "archive.csv",
           [_row("A", "Elsewhere", "Harvard-Westlake School")])
    assert load_winner_corpus(str(tmp_path)) == {}
