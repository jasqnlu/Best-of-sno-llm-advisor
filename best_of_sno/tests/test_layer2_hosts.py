"""Tests for the host-parameterized backfill helpers (Layer 2, Task 1)."""

import pytest

from best_of_sno.backfill import (
    SITEMAP_INDEX,
    _require_iso_date,
    parse_post,
    post_id_from_url,
    sitemap_index_url,
)

POST = (
    b"<html><head><meta property='og:title' content='A Story'></head>"
    b"<body><span class='sno-story-byline'>By Ada Lee, Carlmont High School"
    b" \xe2\x80\xa2 March 3, 2026</span>"
    b"<div class='sno-story-body-content'><p>Body words here.</p></div></body></html>"
)


def test_sitemap_index_url_per_host_and_default_constant_unchanged():
    assert sitemap_index_url("elestoque.org") == "https://elestoque.org/wp-sitemap.xml"
    assert SITEMAP_INDEX == "https://bestofsno.com/wp-sitemap.xml"


def test_post_id_default_host_is_bestofsno():
    assert (
        post_id_from_url("https://bestofsno.com/89942/arts/scene-around/")
        == "https://bestofsno.com/?p=89942"
    )


def test_post_id_honors_host_so_ids_never_collide_across_sites():
    assert (
        post_id_from_url("https://scotscoop.com/50/news/x/", host="scotscoop.com")
        == "https://scotscoop.com/?p=50"
    )
    assert (
        post_id_from_url("https://elestoque.org/50/news/x/", host="elestoque.org")
        == "https://elestoque.org/?p=50"
    )


def test_parse_post_threads_host_into_id():
    r = parse_post(
        POST, "https://scotscoop.com/50/news/x/", "NOW",
        since="2026-01-01", host="scotscoop.com",
    )
    assert r["id"] == "https://scotscoop.com/?p=50"
    assert r["published"] == "2026-03-03" and r["author"] == "Ada Lee"


def test_parse_post_default_host_unchanged():
    r = parse_post(POST, "https://bestofsno.com/50/news/x/", "NOW", since="2026-01-01")
    assert r["id"] == "https://bestofsno.com/?p=50"


@pytest.mark.parametrize("bad", ["2026-1-1", "nope", "", "2026/01/01"])
def test_require_iso_date_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        _require_iso_date(bad, "--until")


def test_require_iso_date_returns_good_value():
    assert _require_iso_date("2026-10-10", "--until") == "2026-10-10"
