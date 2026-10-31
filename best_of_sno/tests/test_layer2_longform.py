"""Long-form (segmented) stories are read; audio/video-led posts are dropped."""

import csv
import json
from pathlib import Path

import pytest

from best_of_sno.layer2 import (
    LAYER2_COLUMNS, MEDIA_MAX_WORDS, UNCERTAIN_COLUMNS, forget_thin, is_media_only,
    main, parse_school_post, run_layer2,
)
from best_of_sno.scraper import COLUMNS

FX = Path(__file__).parent / "fixtures" / "layer2"


def _parse(name, url, host):
    return parse_school_post((FX / name).read_bytes(), url, "NOW",
                             since="2025-01-01", host=host)


# --- long-form segments ------------------------------------------------------

def test_long_form_story_body_comes_from_its_segments():
    # Real Scot Scoop long-form story: no .sno-story-body-content at all.
    # Best of SNO's copy of it has 2,252 words.
    r = _parse("scotscoop_longform.html",
               "https://scotscoop.com/the-euthanasia-paradox-what-does-it-mean-to-say-goodbye/",
               "scotscoop.com")
    assert r["word_count"] > 2000
    assert r["body"].startswith("When a young lady told Coleen Ellis")
    assert set(r) == set(COLUMNS)


def test_every_segment_is_read_in_order_without_photo_credits():
    # Real Burlingame story in three segments; only the first sits inside
    # the .sno-format-slideshow wrapper once the page is parsed.
    r = _parse("theburlingameb_segments.html",
               "https://theburlingameb.org/13050/news/burlingame-remains-confident-in-flock-cameras-despite-security-concerns/",
               "theburlingameb.org")
    body = r["body"]
    assert r["word_count"] > 1500
    assert body.startswith("A network of more than 80,000 cameras")
    assert "Burlingame’s Safeguards" in body  # third segment
    assert body.index("80,000 cameras") < body.index("Burlingame’s Safeguards")
    assert "Jason Lu" not in body  # embed credit


def test_standard_story_body_is_unchanged():
    r = _parse("scotscoop_post.html", "https://scotscoop.com/a/", "scotscoop.com")
    assert r["word_count"] == 133


# --- audio/video-led posts --------------------------------------------------

def test_video_post_is_media_only():
    html = (FX / "torreypinesfalconer_video.html").read_bytes()
    r = parse_school_post(html, "https://torreypinesfalconer.com/14905/falcon-vision/video-troubled-waters/",
                          "NOW", since="2025-01-01", host="torreypinesfalconer.com")
    assert r["word_count"] < MEDIA_MAX_WORDS
    assert is_media_only(html, r["word_count"])


def test_written_feature_with_an_audio_player_is_kept():
    # Real Best of SNO winner: a 2,000-word feature with a SoundCloud player.
    html = (FX / "scotscoop_feature_with_audio.html").read_bytes()
    r = parse_school_post(html, "https://scotscoop.com/the-art-of-preservation-fanmaking-2/",
                          "NOW", since="2025-01-01", host="scotscoop.com")
    assert r["word_count"] > 1500
    assert not is_media_only(html, r["word_count"])


@pytest.mark.parametrize("slug", ["scotscoop", "elestoque", "torreypinesfalconer",
                                  "theburlingameb", "harkeraquila"])
def test_ordinary_articles_are_not_media_only(slug):
    # The El Estoque and Harker fixtures embed YouTube/Spotify/SoundCloud
    # players inside long written articles.
    html = (FX / f"{slug}_post.html").read_bytes()
    r = parse_school_post(html, "https://x.org/1/a/b/", "NOW", since="2025-01-01", host="x.org")
    assert not is_media_only(html, r["word_count"])


def test_a_short_article_without_a_player_is_not_media_only():
    html = (b"<html><body><div class='sno-story-wrap'><div class='sno-story-body-content'>"
            b"<p>A crossword.</p></div></div></body></html>")
    assert not is_media_only(html, 2)


def test_a_player_outside_the_story_is_ignored():
    html = (b"<html><body><div class='sno-story-wrap'><p>Short brief.</p></div>"
            b"<aside><iframe src='https://www.youtube.com/embed/x'></iframe></aside></body></html>")
    assert not is_media_only(html, 2)


def test_an_audio_tag_counts_as_a_player():
    html = (b"<html><body><div class='sno-story-wrap'><audio src='ep1.mp3'></audio>"
            b"<p>Episode notes.</p></div></body></html>")
    assert is_media_only(html, 2)


# --- the crawl drops media-only posts ----------------------------------------

def _archive(tmp_path):
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "archive.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval="")
        w.writeheader()
        w.writerow({"id": "https://bestofsno.com/?p=1", "title": "Early winner",
                    "published": "2025-12-01", "author": "Cy Doe",
                    "school": "Elsewhere High School"})


def _rows(p):
    p = Path(p)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


VIDEO_URL = "https://torreypinesfalconer.com/14905/falcon-vision/video-troubled-waters/"
SITEMAP = (b"<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
           b"<url><loc>" + VIDEO_URL.encode() + b"</loc>"
           b"<lastmod>2026-09-10T10:00:00+00:00</lastmod></url></urlset>")


def test_crawl_drops_a_media_only_post_and_marks_it_done(tmp_path):
    _archive(tmp_path)
    page = (FX / "torreypinesfalconer_video.html").read_bytes()
    run = lambda: run_layer2(str(tmp_path), sites=["torreypinesfalconer.com"], delay=0,
                             until="2026-12-31", fetch_sitemap=lambda *, host: [SITEMAP],
                             fetch_page=lambda u: page)
    res = run()
    assert res["totals"]["dropped_media"] == 1
    assert res["totals"]["non_winner"] == 0 and res["totals"]["uncertain"] == 0
    assert _rows(tmp_path / "data" / "layer2.csv") == []
    assert run()["totals"]["dropped_media"] == 0  # done: not fetched again


# --- forgetting thin rows so the next crawl re-fetches them --------------------

def _write(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="")
        w.writeheader()
        w.writerows(rows)


def _seed_thin(tmp_path):
    _archive(tmp_path)
    d = tmp_path / "data"
    _write(d / "layer2.csv", [
        {"id": "T1", "source_site": "scotscoop.com", "word_count": "0", "label": "winner"},
        {"id": "T2", "source_site": "scotscoop.com", "word_count": "55", "label": "non_winner"},
        {"id": "K1", "source_site": "scotscoop.com", "word_count": "800", "label": "non_winner"},
        {"id": "E1", "source_site": "elestoque.org", "word_count": "10", "label": "non_winner"},
    ], LAYER2_COLUMNS)
    _write(d / "uncertain.csv", [
        {"id": "U1", "source_site": "scotscoop.com", "word_count": "9", "label": "uncertain",
         "reason": "undated"},
    ], UNCERTAIN_COLUMNS)
    (d / "layer2_state.json").write_text(
        json.dumps({"done_ids": ["T1", "T2", "K1", "E1", "U1", "OUT"]}))


def test_forget_thin_removes_short_rows_for_the_chosen_sites(tmp_path):
    _seed_thin(tmp_path)
    assert forget_thin(str(tmp_path), sites=["scotscoop.com"]) == 3
    d = tmp_path / "data"
    assert {r["id"] for r in _rows(d / "layer2.csv")} == {"K1", "E1"}
    assert _rows(d / "uncertain.csv") == []
    done = set(json.loads((d / "layer2_state.json").read_text())["done_ids"])
    assert done == {"K1", "E1", "OUT"}  # out-of-window drops stay done


def test_forget_thin_defaults_to_every_site(tmp_path):
    _seed_thin(tmp_path)
    assert forget_thin(str(tmp_path)) == 4
    assert {r["id"] for r in _rows(tmp_path / "data" / "layer2.csv")} == {"K1"}


def test_main_refetch_thin_forgets_then_crawls(tmp_path, monkeypatch):
    _seed_thin(tmp_path)
    calls = []

    def fake_sitemaps(*, host, **kw):
        calls.append(host)
        return []

    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps", fake_sitemaps)
    assert main(["--data-dir", str(tmp_path), "--sites", "scotscoop.com",
                 "--refetch-thin", "--delay", "0"]) == 0
    assert calls == ["scotscoop.com"]
    assert {r["id"] for r in _rows(tmp_path / "data" / "layer2.csv")} == {"K1", "E1"}
