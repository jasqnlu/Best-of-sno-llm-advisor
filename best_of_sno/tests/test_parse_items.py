"""Tests for parse_items: feed bytes -> record dicts (Task 2)."""

from pathlib import Path

from best_of_sno.scraper import COLUMNS, parse_items

FIXTURE = Path(__file__).parent / "fixtures" / "feed_sample.xml"
SCRAPED_AT = "2026-10-28T08:00:00-07:00"


def _records():
    return parse_items(FIXTURE.read_bytes(), SCRAPED_AT)


def test_parses_all_items():
    assert len(_records()) == 3


def test_normal_item_fields():
    r = _records()[0]
    assert set(r.keys()) == set(COLUMNS)
    assert r["id"] == "https://bestofsno.com/?p=100"
    assert r["url"] == "https://bestofsno.com/100/features/normal-story/"
    assert r["title"] == "Normal Story"
    assert r["author"] == "Jane Doe"
    assert r["school"] == "Example High School"
    assert r["categories"] == "Features;Showcase"
    assert r["source_site"] == "examplehigh.org"
    assert r["word_count"] > 0
    assert r["published"].startswith("2026-10-15")
    assert r["scraped_at"] == SCRAPED_AT


def test_excerpt_only_item_has_empty_body():
    r = _records()[2]
    assert r["body"] == ""
    assert r["word_count"] == 0
    assert r["source_site"] == ""
    assert r["summary"] != ""  # the excerpt still comes through


def test_multi_author_item_has_no_school():
    r = _records()[1]
    assert r["school"] == ""
    assert "," in r["author"]
    assert r["source_site"] == ""  # only a bestofsno-hosted image
