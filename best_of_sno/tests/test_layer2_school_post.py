"""Layer 2 per-site identity + parsing fallbacks (found during Task 2 capture)."""

from best_of_sno.layer2 import parse_school_post, post_id

NOW = "2026-10-29T08:00:00-07:00"

HARKER = (
    b"<html><head>"
    b"<meta property='og:title' content='Honor Week begins - Harker Aquila'>"
    b"<meta property='og:site_name' content='Harker Aquila'>"
    b"</head><body><span class='sno-story-byline'>by Sanyi Yao and Sophia Xu</span>"
    b"<span class='sno-story-date'>October 29, 2026</span>"
    b"<div class='sno-story-body-content'><p>Students wrote responses.</p></div>"
    b"</body></html>"
)
H_URL = "https://harkeraquila.com/100825/news/honor-week-begins/"


def test_post_id_numeric_permalink_uses_the_wp_post_id():
    assert (
        post_id("https://torreypinesfalconer.com/16371/news/pope/", "torreypinesfalconer.com")
        == "https://torreypinesfalconer.com/?p=16371"
    )


def test_post_id_slug_permalink_uses_the_canonical_url():
    assert (
        post_id("https://scotscoop.com/cartoon-superman-is-an-immigrant/", "scotscoop.com")
        == "https://scotscoop.com/cartoon-superman-is-an-immigrant/"
    )


def test_post_id_date_permalinks_never_collide_on_the_year():
    # El Estoque: /YYYY/MM/DD/... — the 1st segment is the YEAR, so the
    # `?p=<1st segment>` scheme would give every 2026 article the same id.
    a = post_id("https://elestoque.org/2026/01/13/entertainment/marty/", "elestoque.org")
    b = post_id("https://elestoque.org/2026/02/02/news/other/", "elestoque.org")
    assert a != b
    assert "?p=2026" not in a and "?p=2026" not in b


def test_post_id_four_digit_id_without_a_date_path_is_still_a_post_id():
    assert (
        post_id("https://example.org/2019/news/slug/", "example.org")
        == "https://example.org/?p=2019"
    )


def test_date_falls_back_to_sno_story_date():
    r = parse_school_post(HARKER, H_URL, NOW, since="2026-01-01", host="harkeraquila.com")
    assert r["published"] == "2026-10-29"
    assert r["author"] == "Sanyi Yao and Sophia Xu"


def test_fallback_date_is_still_gated_by_since():
    assert parse_school_post(HARKER, H_URL, NOW, since="2027-01-01",
                             host="harkeraquila.com") is None


def test_site_name_suffix_is_stripped_from_the_title():
    r = parse_school_post(HARKER, H_URL, NOW, since="2026-01-01", host="harkeraquila.com")
    assert r["title"] == "Honor Week begins"


def test_title_dash_that_is_not_the_site_name_is_kept():
    html = HARKER.replace(b"Honor Week begins - Harker Aquila", b"Q&amp;A - Part two")
    r = parse_school_post(html, H_URL, NOW, since="2026-01-01", host="harkeraquila.com")
    assert r["title"] == "Q&A - Part two"


def test_id_comes_from_post_id():
    r = parse_school_post(HARKER, H_URL, NOW, since="2026-01-01", host="harkeraquila.com")
    assert r["id"] == "https://harkeraquila.com/?p=100825"
    assert r["word_count"] > 0
