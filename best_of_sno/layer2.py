"""School-site non-winner collection (Layer 2).

Crawls five SNO-platform high-school news sites, labels each article
winner / non_winner / uncertain against the Layer 1 winners corpus, and
writes the training data for the chance-score model. Enumeration, fetching
and post parsing are reused from ``backfill``. See
docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md.
"""

from __future__ import annotations

import csv
import difflib
import html
import io
import logging
import os
import re
import unicodedata
from typing import NamedTuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import backfill, scraper

LOG = logging.getLogger("best_of_sno.layer2")

# Crawled host -> school name exactly as it appears in the winners corpus
# (verified against archive.csv 2026-10-29: 61 / 14 / 9 / 9 / 7 winners).
SITES = {
    "scotscoop.com": "Carlmont High School",
    "elestoque.org": "Monta Vista High School",
    "torreypinesfalconer.com": "Torrey Pines High School",
    "theburlingameb.org": "Burlingame High School",
    "harkeraquila.com": "The Harker School",
}

# Each winner lives in exactly one of these (run_backfill skips ids already
# in new/old), so the answer key is their union — never archive.csv alone.
CORPUS_FILES = ("archive.csv", "new.csv", "old.csv")
_CORPUS_FIELDS = ("id", "url", "title", "published", "author")

# WordPress date permalinks (/%year%/%monthnum%/...) put the YEAR first,
# which must never be mistaken for a numeric post id.
_DATE_PERMALINK_RE = re.compile(r"^\d{4}/\d{2}/")

# Separators a theme puts between a headline and the site name in og:title.
_TITLE_SITE_SEPARATORS = (" - ", " | ", " – ", " — ")


def post_id(url: str, host: str) -> str:
    """Stable, per-host id for a school-site post.

    Numeric permalinks (``/16371/news/slug/``) keep the daily-feed guid
    scheme ``https://<host>/?p=16371``. Slug or date permalinks
    (``/slug/``, ``/2026/01/13/news/slug/``) have no post id in the URL, so
    the canonical URL itself is the id — otherwise every 2026 date-permalink
    article would share ``?p=2026``.
    """
    path = urlparse(url).path.strip("/")
    first = path.split("/")[0]
    if first.isdigit() and not _DATE_PERMALINK_RE.match(path + "/"):
        return f"https://{host}/?p={first}"
    return f"https://{host}/{path}/"


def _strip_site_suffix(title: str, site_name: str) -> str:
    """Drop a trailing ``" - <site name>"`` (or ``|``/en/em dash) from a title."""
    if site_name:
        for sep in _TITLE_SITE_SEPARATORS:
            if title.endswith(sep + site_name):
                return title[: -len(sep + site_name)].rstrip()
    return title


def parse_school_post(
    html: bytes, url: str, scraped_at: str, *, since: str, host: str
) -> dict | None:
    """``backfill.parse_post`` plus the fallbacks school-site themes need.

    Some sites put the date in ``.sno-story-date`` instead of after the
    byline's bullet, and append the site name to ``og:title``. Fills the
    date from ``.sno-story-date`` when the byline gave none (re-applying the
    ``since`` gate), strips the site-name suffix so titles match the
    archive's, and sets ``id`` via ``post_id``.
    """
    record = backfill.parse_post(html, url, scraped_at, since=since, host=host)
    if record is None:
        return None
    soup = BeautifulSoup(html, "html.parser")

    if not record["published"]:
        date_el = soup.select_one(".sno-story-date")
        if date_el is not None:
            record["published"] = backfill._date_to_iso(date_el.get_text(" ", strip=True))
            if record["published"] and record["published"] < since:
                return None

    site = soup.find("meta", attrs={"property": "og:site_name"})
    site_name = ((site.get("content") if site else "") or "").strip()
    record["title"] = _strip_site_suffix(record["title"], site_name)
    record["id"] = post_id(url, host)
    return record


# difflib ratio at or above which two normalized titles are a near-match.
# Pinned against the real archive: across all 2,014 intra-school pairs of
# winner titles, the closest pair of DISTINCT titles scores 0.849 ("The art
# of preservation: Fanmaking" vs "...: Glass eye making"), so 0.90 clears
# every real negative while 0.85 would not.
NEARMATCH_RATIO = 0.90

_WS_RE = re.compile(r"\s+")


class Verdict(NamedTuple):
    """How one school-site article is labeled against the winners corpus."""

    label: str  # "winner" | "non_winner" | "uncertain"
    matched_id: str  # corpus id of the exact match, else ""
    reason: str  # "" | "undated" | "title-nearmatch" | "author-date" | "title-ambiguous"
    candidate_title: str
    candidate_url: str


def normalize_title(title: str | None) -> str:
    """Comparable form of a title: entities unescaped, every Unicode
    punctuation mark replaced by a space (so "art—the" does not weld into
    one word, and "don't" / "don’t" both become "don t"), whitespace
    collapsed, lowercased."""
    text = html.unescape(title or "")
    text = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)
    return _WS_RE.sub(" ", text).strip().lower()


def _same_author(winner_author: str, record_author: str) -> bool:
    """True if the winner's author appears as whole words in the record's.

    School-site bylines can carry a staff role ("Liana Barooah , Sports and
    Photo Editor") that the Best of SNO byline does not, so equality would
    miss; whole-token containment matches the name without letting "Sam Li"
    match "Sam Lin".
    """
    wa, ra = normalize_title(winner_author), normalize_title(record_author)
    return bool(wa) and f" {wa} " in f" {ra} "


def _same_author_and_date(winner: dict, record: dict) -> bool:
    # [:10] because daily-scraper corpus rows store a full ISO datetime
    # while backfilled and school-site rows store YYYY-MM-DD.
    return (
        _same_author(winner["author"], record["author"])
        and bool(record["published"])
        and winner["published"][:10] == record["published"][:10]
    )


def _uncertain(reason: str, winner: dict) -> Verdict:
    return Verdict("uncertain", winner["id"], reason, winner["title"], winner["url"])


def classify(record: dict, winners: list[dict]) -> Verdict:
    """Label ``record`` against its school's corpus winners (spec §6.4).

    ``winners`` rows carry ``id``, ``url``, ``title``, ``published``,
    ``author`` and a precomputed ``norm_title``. Rules, in order: undated ->
    uncertain; one exact normalized-title match -> winner; several -> the one
    sharing author+date, else uncertain; a near-match title -> uncertain; a
    winner sharing author+date under a different title -> uncertain;
    otherwise non_winner. The record's own ``school`` cell is never read —
    the caller picks ``winners`` by host.
    """
    if not record["published"]:
        return Verdict("uncertain", "", "undated", "", "")

    title = normalize_title(record["title"])
    exact = [w for w in winners if w["norm_title"] == title]
    if len(exact) == 1:
        return Verdict("winner", exact[0]["id"], "", "", "")
    if exact:
        corroborated = [w for w in exact if _same_author_and_date(w, record)]
        if len(corroborated) == 1:
            return Verdict("winner", corroborated[0]["id"], "", "", "")
        return _uncertain("title-ambiguous", exact[0])

    best, best_ratio = None, 0.0
    for w in winners:
        ratio = difflib.SequenceMatcher(None, title, w["norm_title"]).ratio()
        if ratio > best_ratio:
            best, best_ratio = w, ratio
    if best is not None and best_ratio >= NEARMATCH_RATIO:
        return _uncertain("title-nearmatch", best)

    for w in winners:
        if _same_author_and_date(w, record):
            return _uncertain("author-date", w)
    return Verdict("non_winner", "", "", "", "")


def load_winner_corpus(data_dir: str) -> dict[str, list[dict]]:
    """Index the winners corpus (archive ∪ new ∪ old) by school name.

    Keeps only the schools in ``SITES`` and projects each row to the lookup
    fields plus a precomputed ``norm_title``; the body is dropped so the
    ~11 MB archive is not held in memory through a multi-hour crawl.
    Missing files are skipped.
    """
    schools = set(SITES.values())
    corpus: dict[str, list[dict]] = {}
    for name in CORPUS_FILES:
        for row in scraper._read_rows(os.path.join(data_dir, "data", name)):
            if row.get("school") not in schools:
                continue
            winner = {field: row.get(field) or "" for field in _CORPUS_FIELDS}
            winner["norm_title"] = normalize_title(winner["title"])
            corpus.setdefault(row["school"], []).append(winner)
    return corpus


# Archive schema + label columns, appended never substituted (spec §4), so
# Layers 3-4 can read archive.csv and layer2.csv as one corpus.
LAYER2_COLUMNS = scraper.COLUMNS + ["label", "matched_id"]
UNCERTAIN_COLUMNS = LAYER2_COLUMNS + ["reason", "candidate_title", "candidate_url"]


def _rows_to_csv_text(records: list[dict], columns: list[str]) -> str:
    """Render records under ``columns`` in the archive's dialect
    (QUOTE_MINIMAL), each cell guarded against formula injection."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, restval="", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(
        {key: scraper._csv_safe(val) for key, val in record.items()} for record in records
    )
    return buf.getvalue()


def append_rows(path: str, records: list[dict], columns: list[str]) -> None:
    """Append ``records`` to the CSV at ``path`` under ``columns``, crash-safe.

    Same read-existing + atomic rewrite as ``backfill.append_rows``, but
    bound to Layer 2's wider column lists — the backfill's writer is fixed
    to the 12 archive columns and would silently drop the label fields.
    """
    if not records:
        return
    existing = scraper._read_rows(path)
    scraper._atomic_write_text(path, _rows_to_csv_text(existing + records, columns))


# The checkpoint is the backfill's format exactly ({"done_ids": [...]}).
load_layer2_state = backfill.load_backfill_state
save_layer2_state = backfill.save_backfill_state
