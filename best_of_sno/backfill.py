"""Historical backfill of Best of SNO winners (Layer 1).

Enumerates posts from the WordPress sitemap, filters to a date window, and
(in later tasks) fetches each post's HTML page to build archive.csv rows
that match the daily scraper's schema. See
docs/superpowers/specs/2026-10-29-layer1-historical-backfill-design.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# defusedxml hardens against XXE / billion-laughs entity attacks; the stdlib
# ElementTree parser is vulnerable by default. Sitemaps are fetched over the
# network, so we parse them defensively even though the source is trusted.
import defusedxml.ElementTree as ET

from . import scraper

LOG = logging.getLogger("best_of_sno.backfill")



def sitemap_index_url(host: str) -> str:
    """The WordPress sitemap index for ``host`` (every SNO site shares it)."""
    return f"https://{host}/wp-sitemap.xml"


SITEMAP_INDEX = sitemap_index_url("bestofsno.com")

# The bullet separating "By Author, School" from the date in .sno-story-byline.
_BYLINE_BULLET = "•"
_DATE_FORMAT = "%B %d, %Y"  # e.g. "October 28, 2026"

# WordPress sitemap namespace.
_SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def parse_sitemap(xml_bytes: bytes) -> list[tuple[str, str]]:
    """Parse a sitemap (or sub-sitemap) into ``(loc, lastmod)`` pairs.

    ``lastmod`` is the raw ISO string from the sitemap (empty if absent).
    """
    root = ET.fromstring(xml_bytes)
    pairs: list[tuple[str, str]] = []
    for url in root.findall(f"{_SM_NS}url"):
        loc_el = url.find(f"{_SM_NS}loc")
        if loc_el is None or not (loc_el.text or "").strip():
            continue
        mod_el = url.find(f"{_SM_NS}lastmod")
        lastmod = (mod_el.text or "").strip() if mod_el is not None else ""
        pairs.append((loc_el.text.strip(), lastmod))
    return pairs


def select_candidates(pairs: list[tuple[str, str]], since: str) -> list[str]:
    """Keep locs whose ``lastmod >= since``, preserving input order.

    ISO-8601 date strings compare correctly as plain strings, so a
    ``since`` of ``"2026-01-01"`` matches any lastmod in 2026 or later.
    A missing lastmod is treated as out of window (dropped).
    """
    return [loc for loc, lastmod in pairs if lastmod and lastmod >= since]


def post_id_from_url(url: str, *, host: str = "bestofsno.com") -> str:
    """Build the daily-feed guid scheme from a post URL.

    ``https://bestofsno.com/89942/arts-entertainment/scene-around/`` ->
    ``https://bestofsno.com/?p=89942``, so backfilled rows dedup against
    the daily scraper's ids. Layer 2 passes each school's ``host`` so ids
    from different sites never collide.
    """
    numeric = urlparse(url).path.strip("/").split("/")[0]
    return f"https://{host}/?p={numeric}"


def _category_from_url(url: str) -> str:
    """Deslugify the 2nd path segment into a best-effort category name.

    ``.../89942/arts-entertainment/scene-around/`` -> ``"Arts Entertainment"``.
    SNO post pages carry no category links or published-time meta on this
    theme, so the URL is the reliable category source.
    """
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) < 2 or not parts[1]:
        return ""
    return parts[1].replace("-", " ").title()


def _parse_byline_block(text: str) -> tuple[str, str]:
    """Split a ``.sno-story-byline`` into ``(byline, date_str)`` on the bullet.

    ``"By Madison Shen, Harvard-Westlake School • October 28, 2026"`` ->
    ``("By Madison Shen, Harvard-Westlake School", "October 28, 2026")``.
    No bullet -> the whole text is the byline and the date is empty.
    """
    if _BYLINE_BULLET in text:
        byline, _, date_str = text.rpartition(_BYLINE_BULLET)
        return (byline.strip(), date_str.strip())
    return (text.strip(), "")


def _date_to_iso(date_str: str) -> str:
    """``"October 28, 2026"`` -> ``"2026-10-28"``; empty on any parse failure."""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, _DATE_FORMAT).date().isoformat()
    except ValueError:
        LOG.warning("unparseable byline date: %r", date_str)
        return ""


def parse_post(
    html: bytes, url: str, scraped_at: str, *, since: str, host: str = "bestofsno.com"
) -> dict | None:
    """Parse one post HTML page into a record keyed by ``scraper.COLUMNS``.

    Returns ``None`` when the parsed published date is a valid date before
    ``since`` (the published-date gate catches pre-window posts that passed
    the sitemap's ``lastmod`` prefilter). A missing or unparseable byline
    never drops the story: author/school/published are left empty and the
    body — the fine-tuning signal — is still captured. ``host`` only sets
    the ``id`` scheme (see ``post_id_from_url``).
    """
    soup = BeautifulSoup(html, "html.parser")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    title = (og_title.get("content") if og_title else "") or ""

    og_desc = soup.find("meta", attrs={"property": "og:description"})
    summary = (og_desc.get("content") if og_desc else "") or ""

    byline_el = soup.select_one(".sno-story-byline")
    if byline_el is not None:
        byline, date_str = _parse_byline_block(byline_el.get_text(" ", strip=True))
        author, school = scraper.parse_byline(byline)
        published = _date_to_iso(date_str)
    else:
        LOG.warning("no .sno-story-byline on %s", url)
        author, school, published = "", "", ""

    # Published-date gate: a valid date before the window means a pre-window
    # post whose lastmod slipped past the prefilter. Drop it.
    if published and published < since:
        return None

    # article:section carries the real category name (ampersand intact),
    # matching the daily feed's format; the URL slug is a lossy fallback.
    section = soup.find("meta", attrs={"property": "article:section"})
    categories = (section.get("content") if section else "") or _category_from_url(url)

    body_el = soup.select_one(".sno-story-body-content")
    body_html = body_el.decode_contents() if body_el is not None else ""
    body = scraper.strip_html(body_html)

    return {
        "id": post_id_from_url(url, host=host),
        "url": url,
        "title": title.strip(),
        "published": published,
        "categories": categories,
        "author": author,
        "school": school,
        "summary": scraper.strip_html(summary),
        "body": body,
        "word_count": scraper.word_count(body),
        "source_site": scraper.extract_source_site(body_html),
        "scraped_at": scraped_at,
    }


def append_rows(archive_path: str, records: list[dict]) -> None:
    """Append ``records`` to ``archive.csv``, keeping it crash-safe.

    Implemented as read-existing + atomic full rewrite (not an ``open("a")``
    append) so an interrupt never leaves a half-written row, and the file is
    always a valid CSV with exactly one header. Reuses the daily scraper's
    renderer, so ``archive.csv`` is byte-for-byte the same format and
    formula-injection guard as ``new.csv``/``old.csv``.
    """
    if not records:
        return
    existing = scraper._read_rows(archive_path)
    scraper._atomic_write_text(
        archive_path, scraper._rows_to_csv_text(existing + records)
    )


def load_backfill_state(path: str) -> set[str]:
    """Return the set of post ids already written (``done_ids``).

    Missing or corrupt checkpoint -> empty set, so a fresh or damaged
    checkpoint simply means "nothing done yet".
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return set(data.get("done_ids", []))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def save_backfill_state(path: str, done_ids: set[str]) -> None:
    """Atomically write the checkpoint with ``done_ids`` as a sorted list."""
    scraper._atomic_write_text(
        path, json.dumps({"done_ids": sorted(done_ids)}, indent=2)
    )


def fetch_page(url, *, session=None, timeout=20, retries=3, backoff=2.0) -> bytes:
    """Fetch a post page politely. Delegates to the daily scraper's generic
    GET-with-retries (same UA, timeout, backoff, raise-for-status)."""
    return scraper.fetch_feed(
        url, session=session, timeout=timeout, retries=retries, backoff=backoff
    )


def fetch_all_post_sitemaps(
    *, session=None, host: str = "bestofsno.com", delay: float = 6.0
) -> list[bytes]:
    """Default enumerator: fetch the sitemap index, then every
    ``wp-sitemap-posts-post-*.xml`` sub-sitemap, returning their raw bytes.

    This is the network boundary (like ``scraper.fetch_feed``); tests inject
    a fake in its place. The published-post sitemaps are the only ones we
    need — pages/infobox/taxonomy sitemaps are not winning stories.
    """
    index = fetch_page(sitemap_index_url(host), session=session)
    root = ET.fromstring(index)
    locs = [
        el.text.strip()
        for el in root.iter(f"{_SM_NS}loc")
        if el.text and "posts-post" in el.text
    ]
    out: list[bytes] = []
    for i, loc in enumerate(locs):
        out.append(fetch_page(loc, session=session))
        if i < len(locs) - 1:
            time.sleep(delay)  # Crawl-delay between sitemap fetches too
    return out


_CHECKPOINT_EVERY = 25


def _require_iso_date(value: str, flag: str) -> str:
    """Return ``value`` if it is a zero-padded ISO date, else raise ValueError.

    Dates are compared lexically, which is only correct for zero-padded ISO
    (YYYY-MM-DD). strptime is lenient (it accepts "2026-1-1"), so round-trip
    through strftime and require an exact match — a non-padded date would
    otherwise silently mis-filter instead of erroring.
    """
    try:
        reformatted = datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{flag} must be an ISO date (YYYY-MM-DD): {value!r}") from exc
    if reformatted != value:
        raise ValueError(f"{flag} must be zero-padded (YYYY-MM-DD): {value!r}")
    return value


def run_backfill(
    data_dir: str,
    *,
    since: str = "2026-01-01",
    limit: int | None = None,
    delay: float = 6.0,
    dry_run: bool = False,
    fetch_sitemap=fetch_all_post_sitemaps,
    fetch_page=fetch_page,
    now: str | None = None,
) -> dict:
    """Run the historical backfill (spec §6). Returns counts.

    Enumerate candidates from the sitemaps, drop those already done (the
    checkpoint UNION the ids physically in ``archive.csv`` — same crash-safety
    stance as the daily scraper), then fetch/parse/append each remaining post
    ``delay`` seconds apart. A fetch failure is logged and skipped WITHOUT
    marking the id done, so a later re-run retries it. A parsed pre-window
    post is dropped but marked done. Checkpoint is saved every
    ``_CHECKPOINT_EVERY`` rows and at the end.
    """
    _require_iso_date(since, "--since")

    now = now or datetime.now().astimezone().isoformat()
    data = os.path.join(data_dir, "data")
    archive_path = os.path.join(data, "archive.csv")
    checkpoint_path = os.path.join(data, "backfill_state.json")

    pairs: list[tuple[str, str]] = []
    for xml_bytes in fetch_sitemap():
        pairs.extend(parse_sitemap(xml_bytes))
    in_window = select_candidates(pairs, since)

    res = {
        "candidates": len(in_window),
        "written": 0,
        "skipped": 0,
        "dropped_pre_since": 0,
    }

    if dry_run:
        LOG.info("dry-run: %d candidates in window since %s; nothing written",
                 len(in_window), since)
        return res

    os.makedirs(data, exist_ok=True)
    # Done = the checkpoint, plus every id already stored in any of the four
    # files. Including new.csv/old.csv (not just archive.csv) is the mirror of
    # the daily scraper skipping archived ids: a winner the daily run already
    # captured is never re-written into archive.csv, so each winner lives in
    # exactly one file.
    done = (
        load_backfill_state(checkpoint_path)
        | scraper._read_ids(archive_path)
        | scraper._read_ids(os.path.join(data, "new.csv"))
        | scraper._read_ids(os.path.join(data, "old.csv"))
    )
    todo = [loc for loc in in_window if post_id_from_url(loc) not in done]
    if limit is not None:
        todo = todo[:limit]

    pending_since_save = 0
    for i, loc in enumerate(todo, start=1):
        pid = post_id_from_url(loc)
        if pid in done:
            # A loc duplicated across sitemaps (regenerated mid-enumeration)
            # was already written this run; re-checking `done` here — not only
            # when building `todo` — stops a second identical row.
            continue
        try:
            html = fetch_page(loc)
        except Exception as exc:  # network/HTTP failure after retries
            LOG.warning("fetch failed, skipping (will retry next run): %s (%s)", loc, exc)
            res["skipped"] += 1
            if i < len(todo):
                time.sleep(delay)
            continue

        record = parse_post(html, loc, now, since=since)
        if record is None:
            LOG.info("dropped (published before %s): %s", since, loc)
            res["dropped_pre_since"] += 1
        else:
            append_rows(archive_path, [record])
            res["written"] += 1
        done.add(pid)
        pending_since_save += 1

        if pending_since_save >= _CHECKPOINT_EVERY:
            save_backfill_state(checkpoint_path, done)
            pending_since_save = 0
        LOG.info("fetched %d/%d (written=%d skipped=%d)",
                 i, len(todo), res["written"], res["skipped"])
        if i < len(todo):
            time.sleep(delay)

    save_backfill_state(checkpoint_path, done)
    LOG.info("backfill done: %s", res)
    return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best of SNO historical backfill")
    parser.add_argument("--data-dir", default="best_of_sno", help="folder holding data/ and logs/")
    parser.add_argument("--since", default="2026-01-01", help="ISO date; keep posts published on/after this")
    parser.add_argument("--limit", type=int, default=None, help="cap posts fetched (trial runs)")
    parser.add_argument("--delay", type=float, default=6.0, help="seconds between requests (robots crawl-delay)")
    parser.add_argument("--dry-run", action="store_true", help="enumerate + report; fetch/write nothing")
    args = parser.parse_args(argv)

    logs = os.path.join(args.data_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(logs, "backfill.log")),
            logging.StreamHandler(),
        ],
    )
    res = run_backfill(
        args.data_dir, since=args.since, limit=args.limit,
        delay=args.delay, dry_run=args.dry_run,
    )
    LOG.info("result: %s", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
