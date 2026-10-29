"""Integration tests for run_backfill: enumerate, resume, failures (Task 5)."""

import csv
from pathlib import Path

import pytest

from best_of_sno.backfill import run_backfill

FX = Path(__file__).parent / "fixtures" / "backfill"
SM = (FX / "sitemap_sample.xml").read_bytes()  # 2 in-window, 1 pre-2026
PAGES = {
    "https://bestofsno.com/89942/arts-entertainment/scene-around/": (
        FX / "post_89942_single_author.html"
    ).read_bytes(),
    "https://bestofsno.com/89941/sports/still-in-the-game/": (
        FX / "post_89941_single_author.html"
    ).read_bytes(),
}


def fake_sitemap():
    return [SM]  # one sub-sitemap


def fake_page(url):
    if url not in PAGES:
        raise RuntimeError("boom")
    return PAGES[url]


def _rows(p):
    return (
        list(csv.DictReader(open(p, newline="", encoding="utf-8")))
        if Path(p).exists()
        else []
    )


def test_run_writes_in_window_rows(tmp_path):
    res = run_backfill(
        str(tmp_path), since="2026-01-01", delay=0,
        fetch_sitemap=fake_sitemap, fetch_page=fake_page,
    )
    rows = _rows(tmp_path / "data" / "archive.csv")
    assert res["candidates"] == 2 and res["written"] == 2
    assert {r["id"] for r in rows} == {
        "https://bestofsno.com/?p=89942",
        "https://bestofsno.com/?p=89941",
    }


def test_dry_run_writes_nothing(tmp_path):
    res = run_backfill(
        str(tmp_path), delay=0, dry_run=True,
        fetch_sitemap=fake_sitemap, fetch_page=fake_page,
    )
    assert res["candidates"] == 2
    assert not (tmp_path / "data" / "archive.csv").exists()


def test_resume_skips_done_ids(tmp_path):
    run_backfill(
        str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=fake_page
    )
    calls = []

    def counting_page(url):
        calls.append(url)
        return fake_page(url)

    res2 = run_backfill(
        str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=counting_page
    )
    assert calls == [] and res2["written"] == 0
    assert len(_rows(tmp_path / "data" / "archive.csv")) == 2  # still 2, no dup


def test_fetch_failure_is_skipped_not_fatal_and_retried_next_run(tmp_path):
    bad_url = "https://bestofsno.com/89941/sports/still-in-the-game/"

    def flaky(url):
        if url == bad_url:
            raise RuntimeError("boom")
        return PAGES[url]

    res = run_backfill(
        str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=flaky
    )
    assert res["written"] == 1 and res["skipped"] == 1  # one survived, one skipped
    # the skipped id was NOT marked done -> a good re-run picks it up
    res2 = run_backfill(
        str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=fake_page
    )
    assert res2["written"] == 1
    assert len(_rows(tmp_path / "data" / "archive.csv")) == 2


def test_run_backfill_rejects_non_iso_since(tmp_path):
    # A non-zero-padded --since would silently mis-filter (lexical date
    # compare), so it must be rejected rather than produce wrong results.
    with pytest.raises(ValueError):
        run_backfill(
            str(tmp_path), since="2026-1-1", delay=0,
            fetch_sitemap=fake_sitemap, fetch_page=fake_page,
        )


_DUP_SM = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://bestofsno.com/89942/arts-entertainment/scene-around/</loc><lastmod>2026-10-28T16:08:34+00:00</lastmod></url>
<url><loc>https://bestofsno.com/89942/arts-entertainment/scene-around/</loc><lastmod>2026-10-28T16:08:34+00:00</lastmod></url>
</urlset>"""


def test_duplicate_loc_written_once(tmp_path):
    # A loc appearing twice across sitemaps (e.g. regenerated mid-enumeration)
    # must not produce a duplicate archive row.
    res = run_backfill(
        str(tmp_path), delay=0, fetch_sitemap=lambda: [_DUP_SM], fetch_page=fake_page
    )
    assert res["written"] == 1
    assert len(_rows(tmp_path / "data" / "archive.csv")) == 1
