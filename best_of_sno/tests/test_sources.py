"""Cleaning the corpus's source_site column from school names."""

import csv

from best_of_sno import sources
from best_of_sno.scraper import COLUMNS, extract_source_site


def _row(id_, school, host):
    return {"id": id_, "school": school, "source_site": host, "title": id_, "body": "text"}


def test_school_sites_majority_ignores_embeds_and_reports_ties():
    rows = [_row("1", "A", "a.org"), _row("2", "A", "public.flourish.studio"), _row("3", "A", ""),
            _row("4", "A", "a.org"), _row("5", "A", "other.org"),
            _row("6", "B", "b.org"), _row("7", "B", "c.org"),
            _row("8", "C", "public.flourish.studio"), _row("9", "", "x.org")]
    sites = sources.school_sites(rows)
    assert sites["A"] == {"site": "a.org", "winners": 5, "rows_with_site_before": 4,
                          "status": "majority"}
    assert sites["B"]["status"] == "tie" and sites["B"]["site"] == ""
    assert sites["C"]["status"] == "unknown"
    assert "" not in sites


def test_clean_rows_fills_blanks_drops_embeds_and_keeps_unnamed_rows():
    rows = [_row("1", "A", "a.org"), _row("2", "A", "public.flourish.studio"), _row("3", "A", ""),
            _row("4", "B", "b.org"), _row("5", "B", "c.org"),
            _row("6", "", "public.flourish.studio"), _row("7", "", "x.org")]
    changes = sources.clean_rows(rows, sources.school_sites(rows))
    assert [r["source_site"] for r in rows] == ["a.org", "a.org", "a.org", "b.org", "c.org", "", "x.org"]
    assert changes == {"replaced": 1, "filled": 1, "cleared": 1}


def test_run_rewrites_corpus_files_and_writes_school_table(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    for name, rows in (("archive.csv", [_row("1", "A", "a.org"), _row("2", "A", "")]),
                       ("new.csv", [_row("3", "A", "public.flourish.studio")])):
        with open(d / name, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    assert sources.run(str(tmp_path), dry_run=True)["blank_after"] == 0
    assert list(csv.DictReader(open(d / "archive.csv", encoding="utf-8")))[1]["source_site"] == ""

    report = sources.run(str(tmp_path))
    assert report["blank_before"] == 1 and report["blank_after"] == 0
    for name in ("archive.csv", "new.csv"):
        rows = list(csv.DictReader(open(d / name, encoding="utf-8")))
        assert {r["source_site"] for r in rows} == {"a.org"}
        assert list(rows[0]) == COLUMNS
    table = list(csv.DictReader(open(d / "school_sites.csv", encoding="utf-8")))
    assert table == [{"school": "A", "site": "a.org", "winners": "3",
                      "rows_with_site_before": "2", "status": "agreed"}]
    assert sources.run(str(tmp_path))["changes"] == {}          # second run: nothing to do


def test_new_scrapes_skip_chart_embed_hosts():
    html = ('<img src="https://public.flourish.studio/visualisation/1/thumbnail">'
            '<img src="https://public.flourish.studio/visualisation/2/thumbnail">'
            '<img src="https://school.org/wp-content/uploads/a.jpg">')
    assert extract_source_site(html) == "school.org"
