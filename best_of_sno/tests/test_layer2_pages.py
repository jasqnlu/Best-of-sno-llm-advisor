"""Saved raw pages: the crawl keeps each page so --reparse can rebuild rows
with the current parser offline (no re-download)."""

import csv
import gzip
import os

import pytest

from best_of_sno.layer2 import (
    LAYER2_COLUMNS, main, page_path, reparse_saved, run_layer2,
)
from best_of_sno.tests.test_layer2_run import PAGES, _rows, _seed, fake_page, fake_sitemap

URL1 = "https://scotscoop.com/1/news/story-1/"
URL2 = "https://scotscoop.com/2/news/story-2/"


def _crawl(tmp_path, **kw):
    return run_layer2(str(tmp_path), delay=0, fetch_sitemap=fake_sitemap,
                      fetch_page=fake_page, now="NOW", **kw)


def test_page_path_is_per_host_and_readable(tmp_path):
    p = page_path(str(tmp_path), "scotscoop.com", URL1)
    assert p == str(tmp_path / "data" / "pages" / "scotscoop.com" / "1_news_story-1.html.gz")
    assert page_path(str(tmp_path), "harkeraquila.com", "https://harkeraquila.com/") \
        .endswith("harkeraquila.com/index.html.gz")


def test_crawl_saves_every_fetched_page_gzipped(tmp_path):
    _seed(tmp_path)
    _crawl(tmp_path)
    for url in (URL1, URL2):
        with gzip.open(page_path(str(tmp_path), "scotscoop.com", url)) as f:
            assert f.read() == PAGES[url]


def test_dry_run_saves_no_pages(tmp_path):
    _seed(tmp_path)
    _crawl(tmp_path, dry_run=True)
    assert not (tmp_path / "data" / "pages").exists()


def _rewrite(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="")
        w.writeheader()
        w.writerows(rows)


def test_reparse_rebuilds_rows_from_saved_pages(tmp_path):
    _seed(tmp_path)
    _crawl(tmp_path)
    path = tmp_path / "data" / "layer2.csv"
    fresh = {r["url"]: dict(r) for r in _rows(path)}
    stale = [{**r, "body": "stale text", "word_count": "2", "label": "non_winner",
              "matched_id": "", "scraped_at": "THEN"} for r in fresh.values()]
    _rewrite(path, stale, LAYER2_COLUMNS)

    res = reparse_saved(str(tmp_path))

    after = {r["url"]: r for r in _rows(path)}
    assert res["reparsed"] == 2 and res["no_saved_page"] == 0
    for url in (URL1, URL2):
        assert after[url]["body"] == fresh[url]["body"]
        assert after[url]["label"] == fresh[url]["label"]
        assert after[url]["scraped_at"] == "THEN"  # when it was fetched, not now
    assert after[URL1]["label"] == "winner"


def test_reparse_keeps_rows_that_have_no_saved_page(tmp_path):
    _seed(tmp_path)
    _crawl(tmp_path)
    page_path_1 = page_path(str(tmp_path), "scotscoop.com", URL1)
    os.remove(page_path_1)
    path = tmp_path / "data" / "layer2.csv"
    rows = [{**r, "body": "kept as is"} if r["url"] == URL1 else r for r in _rows(path)]
    _rewrite(path, rows, LAYER2_COLUMNS)

    res = reparse_saved(str(tmp_path))

    assert res["no_saved_page"] == 1 and res["reparsed"] == 1
    assert {r["url"]: r["body"] for r in _rows(path)}[URL1] == "kept as is"


def test_main_reparse_fetches_nothing(tmp_path, monkeypatch):
    _seed(tmp_path)
    _crawl(tmp_path)

    def no_network(*a, **kw):
        raise AssertionError("--reparse must not fetch")

    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps", no_network)
    monkeypatch.setattr("best_of_sno.backfill.fetch_page", no_network)
    assert main(["--data-dir", str(tmp_path), "--reparse"]) == 0
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2
