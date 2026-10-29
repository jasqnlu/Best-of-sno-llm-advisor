"""Best of SNO daily scraper (Layer 1).

Pulls newly published Best of SNO stories from the RSS feed and keeps a
de-duplicated, crash-safe CSV archive split into `new` (today's batch) and
`old` (everything earlier). See
docs/superpowers/specs/2026-10-28-best-of-sno-advisor-design.md (§5).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from collections import Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

# Contact-identifying UA, per robots etiquette (design §8).
USER_AGENT = "BestOfSNO-research-scraper (07jasonlu2010@gmail.com)"
# The one allowed, no-query-string path the daily job fetches (design §5.1).
FEED_URL = "https://bestofsno.com/feed/"

# Exact column order for both CSVs (design §5.3 / plan Global Constraints).
COLUMNS = [
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

# Image hosts that reveal the SNO platform / third parties, never the school.
_PLATFORM_HOST_SUFFIXES = (
    "bestofsno.com",
    "wordpress.org",
    "w.org",
    "gravatar.com",
    "gstatic.com",
    "googleapis.com",
)

_WS_RE = re.compile(r"\s+")


def strip_html(html: str | None) -> str:
    """Return the visible text of an HTML fragment, whitespace-collapsed."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    return _WS_RE.sub(" ", text).strip()


def word_count(text: str | None) -> int:
    """Count whitespace-separated tokens in ``text``."""
    if not text:
        return 0
    return len(text.split())


def parse_byline(creator: str | None) -> tuple[str, str]:
    """Split a ``dc:creator`` byline into ``(author, school)``.

    Best-effort: ``"By Name, School"`` yields both; a multi-author list
    (``"By A, B, and C"``) or a lone name yields an empty school rather than
    mistaking a name for a school.
    """
    if not creator:
        return ("", "")
    remainder = re.sub(r"^\s*by\s+", "", creator.strip(), flags=re.IGNORECASE)
    if " and " in remainder:
        return (remainder.strip(), "")
    if "," in remainder:
        author, school = remainder.rsplit(",", 1)
        return (author.strip(), school.strip())
    return (remainder.strip(), "")


def _is_platform_host(host: str) -> bool:
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _PLATFORM_HOST_SUFFIXES
    )


def extract_source_site(body_html: str | None) -> str:
    """Infer the originating school domain from image hosts in the body.

    Best of SNO re-hosts article text but references the school's own media
    library (``<school-domain>/wp-content/uploads/...``). The most common
    non-platform image host is the source site; returns ``""`` if none.
    """
    if not body_html:
        return ""
    soup = BeautifulSoup(body_html, "html.parser")
    hosts: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        host = urlparse(src).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host and not _is_platform_host(host):
            hosts.append(host)
    if not hosts:
        return ""
    return Counter(hosts).most_common(1)[0][0]


def fetch_feed(
    url: str,
    *,
    session=None,
    timeout: int = 20,
    retries: int = 3,
    backoff: float = 2.0,
) -> bytes:
    """GET ``url`` with the contact User-Agent; retry transient failures.

    Retries on any ``requests`` error (connection errors and 4xx/5xx via
    ``raise_for_status``), sleeping ``backoff`` seconds between attempts.
    Returns the raw response bytes; re-raises the last error if all attempts
    fail.
    """
    sess = session or requests.Session()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = sess.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=timeout
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff)
    raise last_exc


def _atomic_write_text(path: str, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file + rename (crash-safe)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.replace(tmp, path)


def _read_ids(path: str) -> set[str]:
    """Return the set of values in the ``id`` column of a CSV (missing → empty)."""
    ids: set[str] = set()
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                value = row.get("id")
                if value:
                    ids.add(value)
    except FileNotFoundError:
        pass
    return ids


def load_state(state_path: str, new_path: str, old_path: str) -> dict:
    """Load ``{last_run, seen_ids}``; rebuild seen_ids from the CSVs if the
    state file is missing or unreadable."""
    try:
        with open(state_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "last_run": data.get("last_run"),
            "seen_ids": set(data.get("seen_ids", [])),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {
            "last_run": None,
            "seen_ids": _read_ids(old_path) | _read_ids(new_path),
        }


def save_state(state_path: str, state: dict) -> None:
    """Atomically write state as JSON, with ``seen_ids`` as a sorted list."""
    payload = {
        "last_run": state.get("last_run"),
        "seen_ids": sorted(state.get("seen_ids", [])),
    }
    _atomic_write_text(state_path, json.dumps(payload, indent=2))


def _rows_to_csv_text(records: list[dict]) -> str:
    """Render records as CSV text with the COLUMNS header."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=COLUMNS, restval="", extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(records)
    return buf.getvalue()


def _read_rows(path: str) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except FileNotFoundError:
        return []


def write_new(new_path: str, records: list[dict]) -> None:
    """Atomically (over)write ``new_path`` with the header + one row per record.

    An empty ``records`` list produces a header-only file.
    """
    _atomic_write_text(new_path, _rows_to_csv_text(records))


def rotate(new_path: str, old_path: str) -> int:
    """Append every data row of ``new_path`` onto ``old_path``, then reset
    ``new_path`` to header-only. Returns the number of rows moved."""
    new_rows = _read_rows(new_path)
    if new_rows:
        _atomic_write_text(old_path, _rows_to_csv_text(_read_rows(old_path) + new_rows))
    write_new(new_path, [])
    return len(new_rows)


def _pubdate_to_iso(pubdate: str | None) -> str:
    """Convert an RFC-822 ``pubDate`` to ISO 8601, keeping the timezone.

    Falls back to the raw string if it cannot be parsed.
    """
    if not pubdate:
        return ""
    try:
        return parsedate_to_datetime(pubdate).isoformat()
    except (TypeError, ValueError):
        return pubdate


def parse_items(feed_bytes: bytes, scraped_at: str) -> list[dict]:
    """Parse raw RSS feed bytes into one record dict per item, keyed by COLUMNS."""
    feed = feedparser.parse(feed_bytes)
    records: list[dict] = []
    for entry in feed.entries:
        raw_body = ""
        if getattr(entry, "content", None):
            raw_body = entry.content[0].get("value") or ""
        author, school = parse_byline(entry.get("author"))
        categories = ";".join(
            tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")
        )
        body = strip_html(raw_body)
        records.append(
            {
                "id": entry.get("id") or entry.get("link", ""),
                "url": entry.get("link", ""),
                "title": entry.get("title", ""),
                "published": _pubdate_to_iso(entry.get("published")),
                "categories": categories,
                "author": author,
                "school": school,
                "summary": strip_html(entry.get("summary")),
                "body": body,
                "word_count": word_count(body),
                "source_site": extract_source_site(raw_body),
                "scraped_at": scraped_at,
            }
        )
    return records
