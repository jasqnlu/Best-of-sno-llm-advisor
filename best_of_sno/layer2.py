"""School-site non-winner collection (Layer 2).

Crawls five SNO-platform high-school news sites, labels each article
winner / non_winner / uncertain against the Layer 1 winners corpus, and
writes the training data for the chance-score model. Enumeration, fetching
and post parsing are reused from ``backfill``. See
docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import backfill

LOG = logging.getLogger("best_of_sno.layer2")

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
