"""Tests for the pure parsing helpers (Task 1)."""

from best_of_sno.scraper import (
    COLUMNS,
    strip_html,
    word_count,
    parse_byline,
    extract_source_site,
)


EXPECTED_COLUMNS = [
    "id",
    "url",
    "title",
    "published",
    "categories",
    "author",
    "school",
    "summary",
    "body",
    "word_count",
    "source_site",
    "scraped_at",
]


def test_columns_order_matches_spec():
    assert COLUMNS == EXPECTED_COLUMNS


def test_strip_html_removes_tags_and_collapses_ws():
    assert strip_html("<p>Hello  <b>world</b></p>\n") == "Hello world"


def test_strip_html_empty():
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_word_count():
    assert word_count("one two three") == 3
    assert word_count("") == 0


def test_parse_byline_author_and_school():
    assert parse_byline("By Talia Rosenthal, Torrey Pines High School") == (
        "Talia Rosenthal",
        "Torrey Pines High School",
    )


def test_parse_byline_multi_author_no_school():
    assert parse_byline("By Ben Balian, Jack Martin, and Will Simpson") == (
        "Ben Balian, Jack Martin, and Will Simpson",
        "",
    )


def test_parse_byline_plain():
    assert parse_byline("By Jane Doe") == ("Jane Doe", "")


def test_extract_source_site_from_image_host():
    html = (
        '<p>x</p><img src="https://torreypinesfalconer.com/wp-content/'
        'uploads/2026/10/a.png"/>'
    )
    assert extract_source_site(html) == "torreypinesfalconer.com"


def test_extract_source_site_ignores_platform_hosts():
    html = (
        '<img src="https://bestofsno.com/x.png"/>'
        '<img src="https://secure.gravatar.com/y.png"/>'
    )
    assert extract_source_site(html) == ""
