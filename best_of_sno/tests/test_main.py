"""Integration tests for run(): wiring, dedup, rotation, dry-run (Task 6)."""

import csv
from pathlib import Path

from best_of_sno.scraper import run

FIXTURE = Path(__file__).parent / "fixtures" / "feed_sample.xml"
NOW = "2026-10-28T08:00:00-07:00"

# A second feed: one already-seen item (102) plus one brand-new item (103).
EXTRA_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Best of SNO</title><link>https://bestofsno.com</link>
  <item>
    <title>Excerpt Only Story</title>
    <link>https://bestofsno.com/102/opinions/excerpt-only-story/</link>
    <dc:creator><![CDATA[By Sam Park, Another School]]></dc:creator>
    <pubDate>Mon, 13 Oct 2026 08:00:00 +0000</pubDate>
    <category><![CDATA[Opinions]]></category>
    <guid isPermaLink="false">https://bestofsno.com/?p=102</guid>
    <description><![CDATA[teaser]]></description>
  </item>
  <item>
    <title>Brand New Story</title>
    <link>https://bestofsno.com/103/news/brand-new-story/</link>
    <dc:creator><![CDATA[By New Writer, New School]]></dc:creator>
    <pubDate>Thu, 16 Oct 2026 10:00:00 +0000</pubDate>
    <category><![CDATA[News]]></category>
    <guid isPermaLink="false">https://bestofsno.com/?p=103</guid>
    <description><![CDATA[excerpt]]></description>
    <content:encoded><![CDATA[<p>Some body words right here.</p>]]></content:encoded>
  </item>
</channel></rss>"""


def _fetch_fixture(url):
    return FIXTURE.read_bytes()


def _rows(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_first_run_fills_new_empty_old(tmp_path):
    res = run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW)
    data = tmp_path / "data"
    assert res["new_found"] == 3
    assert len(_rows(data / "new.csv")) == 3
    assert len(_rows(data / "old.csv")) == 0
    assert (data / "state.json").exists()


def test_second_run_same_feed_rotates_and_dedups(tmp_path):
    run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW)
    res2 = run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW)
    data = tmp_path / "data"
    assert res2["new_found"] == 0
    assert res2["moved_to_old"] == 3
    assert len(_rows(data / "new.csv")) == 0
    assert len(_rows(data / "old.csv")) == 3


def test_dedup_skips_already_seen_guid(tmp_path):
    run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW)
    res = run(str(tmp_path), feed_url="x", fetch=lambda url: EXTRA_FEED, now=NOW)
    data = tmp_path / "data"
    assert res["new_found"] == 1
    new_rows = _rows(data / "new.csv")
    assert len(new_rows) == 1
    assert new_rows[0]["id"].endswith("103")


def test_dry_run_writes_nothing(tmp_path):
    before = _snapshot(tmp_path)
    run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW, dry_run=True)
    assert _snapshot(tmp_path) == before


def test_no_rotate_keeps_old_untouched(tmp_path):
    run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW)
    res = run(str(tmp_path), feed_url="x", fetch=_fetch_fixture, now=NOW, no_rotate=True)
    data = tmp_path / "data"
    assert res["moved_to_old"] == 0
    assert len(_rows(data / "old.csv")) == 0
