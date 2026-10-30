"""Parser-drift proof: real posts from all five Layer 2 sites (Task 2)."""

import re
from pathlib import Path

import pytest

from best_of_sno.backfill import parse_sitemap, select_candidates
from best_of_sno.layer2 import parse_school_post, post_id
from best_of_sno.scraper import COLUMNS

FX = Path(__file__).parent / "fixtures" / "layer2"
SITES = [
    ("scotscoop", "scotscoop.com"),
    ("elestoque", "elestoque.org"),
    ("torreypinesfalconer", "torreypinesfalconer.com"),
    ("theburlingameb", "theburlingameb.org"),
    ("harkeraquila", "harkeraquila.com"),
]


@pytest.mark.parametrize("slug,host", SITES)
def test_parser_handles_every_site(slug, host):
    sm = parse_sitemap((FX / f"{slug}_sitemap.xml").read_bytes())
    locs = select_candidates(sm, since="2026-01-01")
    assert len(locs) == 2  # the 2025 entry is dropped
    r = parse_school_post(
        (FX / f"{slug}_post.html").read_bytes(), locs[0], "NOW",
        since="2026-01-01", host=host,
    )
    assert r is not None, f"{host}: parse_post dropped an in-window post"
    assert set(r) == set(COLUMNS)
    assert r["id"] == post_id(locs[0], host)
    assert r["title"].strip(), f"{host}: no og:title"
    assert not r["title"].endswith(" - Harker Aquila")  # site suffix stripped
    assert r["word_count"] > 50, f"{host}: body too short — selector drift"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["published"]), f"{host}: byline date unparsed"
    assert r["author"].strip(), f"{host}: byline author unparsed"


@pytest.mark.parametrize("slug,host", SITES)
def test_every_site_sitemap_url_is_query_free(slug, host):
    for loc, _ in parse_sitemap((FX / f"{slug}_sitemap.xml").read_bytes()):
        assert "?" not in loc  # robots.txt disallows any ?-bearing URL
