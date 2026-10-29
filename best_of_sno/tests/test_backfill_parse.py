"""Tests for the post HTML page parser (Task 2)."""

from pathlib import Path

from best_of_sno.backfill import parse_post
from best_of_sno.scraper import COLUMNS

FX = Path(__file__).parent / "fixtures" / "backfill"
NOW = "2026-10-29T08:00:00-07:00"


def _p(name, url):
    return parse_post((FX / name).read_bytes(), url, NOW, since="2026-01-01")


def test_parse_single_author_full_record():
    r = _p(
        "post_89942_single_author.html",
        "https://bestofsno.com/89942/arts-entertainment/scene-around/",
    )
    assert set(r) == set(COLUMNS)
    assert r["id"] == "https://bestofsno.com/?p=89942"
    assert r["title"] == "Scene Around"  # from og:title, not <h1>
    assert r["author"] == "Madison Shen"
    assert r["school"] == "Harvard-Westlake School"
    assert r["published"].startswith("2026-10-28")
    assert r["categories"]  # non-empty, from URL segment
    assert r["word_count"] > 0 and r["body"]


def test_parse_multi_author_has_no_school():
    r = _p(
        "post_89940_multi_author.html",
        "https://bestofsno.com/89940/showcase/women-are-freaking-magical-frenchtown-coven-performs-annual-witches-dance/",
    )
    assert "Emma Haig" in r["author"] and "Riley Nelson" in r["author"]
    assert r["school"] == ""  # "and"-list -> empty school


def test_parse_preserves_non_ascii_title():
    r = _p("post_89940_multi_author.html", "https://bestofsno.com/89940/showcase/x/")
    assert "magical" in r["title"].lower()  # smart-quoted title survives


def test_published_gate_drops_pre_since():
    # since in the future -> the 2026-10-28 story is before it -> dropped.
    r = parse_post(
        (FX / "post_89942_single_author.html").read_bytes(),
        "https://bestofsno.com/89942/a/b/",
        NOW,
        since="2027-01-01",
    )
    assert r is None


def test_missing_byline_keeps_body_empty_meta():
    html = (
        b"<html><head><meta property='og:title' content='No Byline'></head>"
        b"<body><div class='sno-story-body-content'><p>Body words here.</p></div></body></html>"
    )
    r = parse_post(html, "https://bestofsno.com/777/news/x/", NOW, since="2026-01-01")
    assert r["title"] == "No Byline" and r["author"] == "" and r["school"] == ""
    assert r["published"] == "" and r["word_count"] > 0


def test_categories_prefer_article_section():
    r = _p(
        "post_89942_single_author.html",
        "https://bestofsno.com/89942/arts-entertainment/scene-around/",
    )
    # article:section carries the real name with the ampersand, matching the
    # daily feed's category format — not the slug-deslugified "Arts Entertainment".
    assert r["categories"] == "Arts & Entertainment"


def test_categories_fall_back_to_url_when_no_section():
    # 89940 has no article:section meta -> URL 2nd-segment deslug.
    r = _p("post_89940_multi_author.html", "https://bestofsno.com/89940/showcase/x/")
    assert r["categories"] == "Showcase"


def test_unparseable_date_keeps_row_empty_published():
    html = (
        b"<html><head><meta property='og:title' content='Weird Date'></head>"
        b"<body><span class='sno-story-byline'>By A, B School \xe2\x80\xa2 someday</span>"
        b"<div class='sno-story-body-content'><p>Words.</p></div></body></html>"
    )
    r = parse_post(html, "https://bestofsno.com/778/news/x/", NOW, since="2026-01-01")
    assert r is not None and r["published"] == "" and r["author"] == "A"
