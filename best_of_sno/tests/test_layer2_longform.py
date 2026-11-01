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


@pytest.mark.parametrize("name,headings", [
    ("scotscoop_longform.html", ["Who cares?", "Walking to the next exam room",
                                 "Soaring vet bills"]),
    ("theburlingameb_segments.html", ["Burlingame’s Flock Cameras",
                                      "The National Security Risks",
                                      "Burlingame’s Safeguards"]),
    ("scotscoop_feature_with_audio.html", [
        "The delicate frontiers of traditional fanmaking and hatmaking",
        "Tutorial: How to make a fan", "Step 1: Choose a reference design",
        "Step 6: Assemble and align"]),
])
def test_section_headings_are_kept_in_reading_order(name, headings):
    # Subheads (h2), segment headings and info-box step titles are part of
    # the story's structure and stay in the body, each before its section.
    body = _parse(name, "https://x.org/a/", "x.org")["body"]
    positions = [body.index(h) for h in headings]
    assert positions == sorted(positions)


def test_gallery_widget_label_is_not_story_text():
    body = _parse("scotscoop_feature_with_audio.html", "https://x.org/a/", "x.org")["body"]
    assert "Gallery •" not in body


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
        {"id": "E1", "source_site": "theburlingameb.org", "word_count": "10", "label": "non_winner"},
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


# --- standard-template body repairs ------------------------------------------

def test_body_survives_a_stray_closing_tag_mid_article():
    # Real Scot Scoop story (a Best of SNO winner, 909 words there). A stray
    # closing tag ends .sno-story-body-content after 142 words; the other
    # paragraphs sit beside it inside .sno-story-body.
    r = _parse("scotscoop_stray_close_tag.html",
               "https://scotscoop.com/a-baby-a-misdiagnosis-and-a-family-torn-apart/",
               "scotscoop.com")
    assert r["word_count"] > 850
    assert r["body"].startswith("Sarah Goble’s son was only two-months-old")
    assert "The judge didn’t ask a single question" in r["body"]
    assert "For Goble, the personal consequences were profound" in r["body"]


def test_inline_gallery_is_dropped_but_the_text_after_it_is_kept():
    # Real Scot Scoop story with a 6-photo gallery between paragraphs. Best of
    # SNO's copy drops the whole gallery: label, photographer and captions.
    r = _parse("scotscoop_inline_gallery.html",
               "https://scotscoop.com/carlmonts-security-cameras-can-recognize-faces-but-most-students-have-no-idea/",
               "scotscoop.com")
    assert "Gallery •" not in r["body"]
    assert "A large Avigilon multisensor dome watches over" not in r["body"]
    assert "Even students who said they broadly support cameras" in r["body"]
    assert r["word_count"] > 2000


def test_body_survives_stray_tags_that_close_every_container():
    # Real Scot Scoop winner (1,569 words on Best of SNO). Its stray tags close
    # .sno-story-body and every container up to <body>, scattering the rest
    # of the story across levels; the share buttons, contributor box and
    # footer that follow it must not be read.
    r = _parse("scotscoop_stray_close_tag_two_levels.html",
               "https://scotscoop.com/after-dark-the-successes-and-challenges-of-night-shift-workers/",
               "scotscoop.com")
    assert r["word_count"] > 1450
    assert "Breathing life Emily Smith was also about to go to sleep" in r["body"]
    assert "The payoff" in r["body"]
    assert "Elias and Smith also saw negative implications" in r["body"]
    assert "“Being on the same page is so important,” Hetherington" in r["body"]
    for chrome in ("Share on Facebook", "About the Contributor", "Carlmont High School 1400", "display: flex"):
        assert chrome not in r["body"]


def test_healthy_page_body_does_not_pick_up_page_chrome():
    r = _parse("scotscoop_post.html", "https://scotscoop.com/x/", "scotscoop.com")
    assert "Share on Facebook" not in r["body"]
    assert "View Story Comments" not in r["body"]


def test_featured_photo_caption_is_not_story_text():
    # Scot Scoop puts the featured photo (photographer + caption) inside the
    # story body; Best of SNO shows it above the story, so its copies start
    # with the first paragraph instead.
    r = _parse("scotscoop_inline_gallery.html",
               "https://scotscoop.com/carlmonts-security-cameras-can-recognize-faces-but-most-students-have-no-idea/",
               "scotscoop.com")
    assert "An Avigilon multisensor camera overlooks a covered walkway" not in r["body"]
    assert r["body"].startswith("A camera is mounted in a white dome above a hallway")


def test_torrey_pines_inline_slideshow_is_dropped_but_figure_captions_kept():
    # Real Torrey Pines winner. Its flexslider gallery (captions plus
    # "Navigate Left Navigate Right") is absent from Best of SNO's copy,
    # while the plain figure captions are kept there.
    r = _parse("torreypinesfalconer_inline_slideshow.html",
               "https://torreypinesfalconer.com/13673/feature/your-face-your-canvas-makeup-as-art-self-expression/",
               "torreypinesfalconer.com")
    assert "Navigate Left" not in r["body"]
    assert "Syd Roenfeldt (11) experiments with goth makeup" not in r["body"]
    assert "Audrey Song (11) likes to express herself" in r["body"]


def test_slideshow_inside_a_long_form_segment_is_dropped():
    # Real Torrey Pines long-form story with a flexslider gallery inside one
    # of its segments.
    r = _parse("torreypinesfalconer_longform_slideshow.html",
               "https://torreypinesfalconer.com/13373/showcase/community-hub-dot-cafe/",
               "torreypinesfalconer.com")
    assert "Navigate Left" not in r["body"]
    assert "It was topped with house-made carrot cake syrup" not in r["body"]
    assert r["word_count"] > 800
