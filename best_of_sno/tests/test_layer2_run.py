"""Integration tests for the per-host crawl + CLI (Layer 2, Task 6)."""

import csv
from pathlib import Path

import pytest

from best_of_sno.layer2 import main, run_layer2
from best_of_sno.scraper import COLUMNS


def _page(title, author="Ada Lee", school="Carlmont High School", date="March 3, 2026"):
    byline = f"By {author}, {school} • {date}" if date else f"By {author}, {school}"
    return (f"<html><head><meta property='og:title' content='{title}'></head><body>"
            f"<span class='sno-story-byline'>{byline}</span>"
            f"<div class='sno-story-body-content'><p>{'word ' * 80}</p></div>"
            f"</body></html>").encode()


def _urlset(locs):
    urls = "".join(
        f"<url><loc>{loc}</loc><lastmod>2026-03-03T10:00:00+00:00</lastmod></url>"
        for loc in locs)
    return (f"<?xml version='1.0'?><urlset "
            f"xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{urls}</urlset>").encode()


def _sitemap(host, ids):
    return _urlset([f"https://{host}/{i}/news/story-{i}/" for i in ids])


def _archive(tmp_path, rows):
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "archive.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval="")
        w.writeheader()
        for r in rows:
            base = {c: "" for c in COLUMNS}
            base.update(r)
            w.writerow(base)


def _rows(p):
    p = Path(p)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# One host, two posts: #1 is a known winner, #2 is not.
PAGES = {
    "https://scotscoop.com/1/news/story-1/": _page("Amputees redefine ability"),
    "https://scotscoop.com/2/news/story-2/": _page("A totally different story", author="Bo Chen"),
}


def fake_sitemap(*, host):
    return [_sitemap(host, [1, 2])]


def fake_page(url):
    if url not in PAGES:
        raise RuntimeError("boom")
    return PAGES[url]


def _seed(tmp_path):
    _archive(tmp_path, [
        {"id": "https://bestofsno.com/?p=83917",
         "url": "https://bestofsno.com/83917/features/amputees/",
         "title": "Amputees redefine ability", "published": "2026-03-03",
         "author": "Ada Lee", "school": "Carlmont High School"},
        # Another school's winner: the archive (backfilled --since 2025-12-01)
        # starts here, which is what the corpus-coverage guard checks.
        {"id": "https://bestofsno.com/?p=80001", "title": "Early winner",
         "published": "2025-12-01", "author": "Cy Doe", "school": "Elsewhere High School"},
    ])


def test_labels_winner_and_non_winner_into_layer2(tmp_path):
    _seed(tmp_path)
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                     fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    rows = {r["id"]: r for r in _rows(tmp_path / "data" / "layer2.csv")}
    assert res["totals"]["winner"] == 1 and res["totals"]["non_winner"] == 1
    assert rows["https://scotscoop.com/?p=1"]["label"] == "winner"
    assert rows["https://scotscoop.com/?p=1"]["matched_id"] == "https://bestofsno.com/?p=83917"
    assert rows["https://scotscoop.com/?p=2"]["label"] == "non_winner"
    # every row carries the SCHOOL-SITE body and the host as source_site
    assert all(r["source_site"] == "scotscoop.com" for r in rows.values())
    assert all(int(r["word_count"]) > 50 for r in rows.values())


def test_school_column_is_the_hosts_school_not_the_byline_role(tmp_path):
    # School-site bylines carry a staff role where Best of SNO has the school.
    _seed(tmp_path)
    pages = {"https://scotscoop.com/5/news/story-5/":
             _page("Some story", author="Bo Chen", school="Copy Editor")}
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=lambda *, host: [_sitemap(host, [5])],
               fetch_page=lambda u: pages[u])
    assert _rows(tmp_path / "data" / "layer2.csv")[0]["school"] == "Carlmont High School"


def test_undated_article_goes_to_uncertain_not_layer2(tmp_path):
    _seed(tmp_path)
    pages = {"https://scotscoop.com/1/news/story-1/":
             _page("Amputees redefine ability", date="")}
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                     fetch_sitemap=lambda *, host: [_sitemap(host, [1])],
                     fetch_page=lambda u: pages[u])
    assert res["totals"]["uncertain"] == 1 and res["totals"]["non_winner"] == 0
    assert _rows(tmp_path / "data" / "layer2.csv") == []
    u = _rows(tmp_path / "data" / "uncertain.csv")[0]
    assert u["reason"] == "undated" and u["label"] == "uncertain"


def test_article_published_after_until_is_dropped(tmp_path):
    _seed(tmp_path)
    pages = {"https://scotscoop.com/9/news/story-9/":
             _page("Late story", date="October 20, 2026")}
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], until="2026-10-10", delay=0,
                     fetch_sitemap=lambda *, host: [_sitemap(host, [9])],
                     fetch_page=lambda u: pages[u])
    assert res["totals"]["dropped_out_of_window"] == 1
    assert _rows(tmp_path / "data" / "layer2.csv") == []


def test_ids_never_collide_across_hosts(tmp_path):
    _seed(tmp_path)
    pages = {"https://scotscoop.com/1/news/story-1/": _page("Scotscoop story", author="Bo Chen"),
             "https://elestoque.org/1/news/story-1/":
                 _page("Estoque story", school="Monta Vista High School")}
    res = run_layer2(str(tmp_path), sites=["scotscoop.com", "elestoque.org"], delay=0,
                     fetch_sitemap=lambda *, host: [_sitemap(host, [1])],
                     fetch_page=lambda u: pages[u])
    ids = {r["id"] for r in _rows(tmp_path / "data" / "layer2.csv")}
    assert ids == {"https://scotscoop.com/?p=1", "https://elestoque.org/?p=1"}
    assert res["totals"]["non_winner"] == 2


def test_date_permalink_articles_are_all_written(tmp_path):
    # El Estoque permalinks start with the year; ?p=<1st segment> would make
    # every 2026 article the same id and drop all but the first as "done".
    _seed(tmp_path)
    locs = ["https://elestoque.org/2026/01/13/news/first/",
            "https://elestoque.org/2026/02/02/news/second/"]
    pages = {locs[0]: _page("First story", author="Bo Chen"),
             locs[1]: _page("Second story", author="Bo Chen")}
    run_layer2(str(tmp_path), sites=["elestoque.org"], delay=0,
               fetch_sitemap=lambda *, host: [_urlset(locs)],
               fetch_page=lambda u: pages[u])
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2


def test_dry_run_writes_nothing(tmp_path):
    _seed(tmp_path)
    fetched = []
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0, dry_run=True,
                     fetch_sitemap=fake_sitemap,
                     fetch_page=lambda u: fetched.append(u) or fake_page(u))
    assert res["sites"]["scotscoop.com"]["candidates"] == 2
    assert fetched == []
    assert not (tmp_path / "data" / "layer2.csv").exists()


def test_resume_refetches_nothing_and_writes_no_duplicate(tmp_path):
    _seed(tmp_path)
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    calls = []
    res2 = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                      fetch_sitemap=fake_sitemap,
                      fetch_page=lambda u: calls.append(u) or fake_page(u))
    assert calls == []
    assert res2["totals"]["winner"] == 0 and res2["totals"]["non_winner"] == 0
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2


def test_resume_works_from_the_csvs_alone(tmp_path):
    _seed(tmp_path)
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    (tmp_path / "data" / "layer2_state.json").unlink()  # lost checkpoint
    calls = []
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=fake_sitemap,
               fetch_page=lambda u: calls.append(u) or fake_page(u))
    assert calls == []
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2


def test_fetch_failure_is_skipped_and_retried_next_run(tmp_path):
    _seed(tmp_path)
    bad = "https://scotscoop.com/2/news/story-2/"

    def flaky(url):
        if url == bad:
            raise RuntimeError("boom")
        return PAGES[url]

    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                     fetch_sitemap=fake_sitemap, fetch_page=flaky)
    assert res["totals"]["skipped"] == 1 and res["totals"]["winner"] == 1
    res2 = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                      fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert res2["totals"]["non_winner"] == 1  # the skipped id was retried
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2


def test_limit_caps_posts_per_site(tmp_path):
    _seed(tmp_path)
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], limit=1, delay=0,
                     fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 1
    assert res["sites"]["scotscoop.com"]["candidates"] == 2


def test_non_iso_until_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_layer2(str(tmp_path), until="2026-1-1", delay=0,
                   fetch_sitemap=fake_sitemap, fetch_page=fake_page)


def test_main_dry_run_returns_zero(tmp_path, monkeypatch):
    # Patches the module attribute, which only works because run_layer2
    # resolves its fetchers at call time rather than at def time.
    _seed(tmp_path)
    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps",
                        lambda **kw: [_sitemap(kw["host"], [1])])
    assert main(["--data-dir", str(tmp_path), "--sites", "scotscoop.com",
                 "--dry-run", "--delay", "0"]) == 0


def test_main_never_touches_the_network_without_a_fake(tmp_path, monkeypatch):
    # Guards the late-binding contract itself: if run_layer2 ever reverts to
    # def-time defaults, this test starts making real HTTP requests instead
    # of raising, and fails loudly.
    def boom(**kw):
        raise AssertionError("real sitemap fetcher was called")

    _seed(tmp_path)
    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps", boom)
    with pytest.raises(AssertionError, match="real sitemap fetcher"):
        main(["--data-dir", str(tmp_path), "--sites", "scotscoop.com", "--dry-run"])


def test_main_rejects_an_unknown_site(tmp_path):
    with pytest.raises(SystemExit):
        main(["--data-dir", str(tmp_path), "--sites", "example.com", "--dry-run"])


def test_crawl_delay_separates_the_sitemap_from_the_first_post_fetch(tmp_path, monkeypatch):
    # robots Crawl-delay: 6 applies to every request on a host, so the
    # last sitemap fetch and the first post fetch must be a delay apart.
    import best_of_sno.layer2 as layer2

    _seed(tmp_path)
    events = []
    monkeypatch.setattr(layer2.time, "sleep", lambda s: events.append(("sleep", s)))

    def sitemap(*, host):
        events.append("sitemap")
        return fake_sitemap(host=host)

    def page(url):
        events.append("fetch")
        return fake_page(url)

    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=6.0,
               fetch_sitemap=sitemap, fetch_page=page)
    assert events == ["sitemap", ("sleep", 6.0), "fetch", ("sleep", 6.0), "fetch"]


def test_default_window_is_december_through_mid_september(tmp_path, monkeypatch):
    # Dec 1: school articles from December can be January Best of SNO
    # winners. Sep 15: today minus the 40-day max republish lag, so every
    # included article has had time to win.
    import best_of_sno.layer2 as layer2

    seen = {}
    monkeypatch.setattr(layer2, "run_layer2", lambda data_dir, **kw: seen.update(kw) or {})
    assert main(["--data-dir", str(tmp_path), "--dry-run"]) == 0
    assert (seen["since"], seen["until"]) == ("2025-12-01", "2026-09-15")
    import inspect
    params = inspect.signature(run_layer2).parameters
    assert (params["since"].default, params["until"].default) == ("2025-12-01", "2026-09-15")


def test_refuses_a_window_that_starts_before_the_winners_corpus(tmp_path):
    # December winners missing from the corpus would be labeled non_winner.
    _archive(tmp_path, [{"id": "W", "title": "T", "published": "2026-01-05",
                         "school": "Carlmont High School"}])
    with pytest.raises(ValueError, match="backfill"):
        run_layer2(str(tmp_path), since="2025-12-01", delay=0,
                   fetch_sitemap=fake_sitemap, fetch_page=fake_page)


def test_tolerates_a_corpus_whose_first_winner_trails_since_by_days(tmp_path):
    # Best of SNO does not publish every day, so the first winner after a
    # --since 2025-12-01 backfill can be dated a few days later.
    _archive(tmp_path, [{"id": "W", "title": "T", "published": "2025-12-03",
                         "school": "Carlmont High School"}])
    res = run_layer2(str(tmp_path), since="2025-12-01", sites=["scotscoop.com"],
                     delay=0, dry_run=True, fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert res["sites"]["scotscoop.com"]["candidates"] == 2


def test_refuses_to_run_without_a_winners_corpus(tmp_path):
    # An empty corpus would label every article non_winner.
    with pytest.raises(ValueError, match="corpus"):
        run_layer2(str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=fake_page)


def test_main_reports_a_window_error_without_a_traceback(tmp_path, capsys, monkeypatch):
    # The fetcher stub keeps this test offline even if the guard regresses.
    def boom(**kw):
        raise AssertionError("real sitemap fetcher was called")

    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps", boom)
    with pytest.raises(SystemExit) as exc:
        main(["--data-dir", str(tmp_path), "--dry-run"])
    assert exc.value.code == 2
    assert "corpus" in capsys.readouterr().err
