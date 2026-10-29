"""Best of SNO daily scraper (Layer 1).

Pulls newly published Best of SNO stories from the RSS feed and keeps a
de-duplicated, crash-safe CSV archive split into `new` (today's batch) and
`old` (everything earlier). See
docs/superpowers/specs/2026-10-28-best-of-sno-advisor-design.md (§5).
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

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
