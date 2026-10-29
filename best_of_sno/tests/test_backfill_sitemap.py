"""Tests for sitemap enumeration + date prefilter (Task 1)."""

from pathlib import Path

from best_of_sno.backfill import parse_sitemap, select_candidates, post_id_from_url

SM = (Path(__file__).parent / "fixtures" / "backfill" / "sitemap_sample.xml").read_bytes()


def test_parse_sitemap_returns_loc_lastmod_pairs():
    pairs = parse_sitemap(SM)
    assert len(pairs) == 3
    assert pairs[0][0].endswith("/scene-around/")
    assert pairs[0][1].startswith("2026-10-28")


def test_select_candidates_keeps_only_in_window():
    pairs = parse_sitemap(SM)
    locs = select_candidates(pairs, since="2026-01-01")
    assert len(locs) == 2  # the 2025 story is dropped
    assert all("50000" not in l for l in locs)


def test_post_id_from_url_matches_feed_guid_scheme():
    assert (
        post_id_from_url("https://bestofsno.com/89942/arts-entertainment/scene-around/")
        == "https://bestofsno.com/?p=89942"
    )
