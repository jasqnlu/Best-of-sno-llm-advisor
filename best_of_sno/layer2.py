"""School-site non-winner collection (Layer 2).

Crawls five SNO-platform high-school news sites, labels each article
winner / non_winner / uncertain against the Layer 1 winners corpus, and
writes the training data for the chance-score model. Enumeration, fetching
and post parsing are reused from ``backfill``. See
docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import io
import logging
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
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
    byline's bullet, an author-less byline holds only its ``.time-wrapper``
    date (no bullet, so ``parse_post`` reads the date as the author), and
    some themes append the site name to ``og:title``. When the byline gave
    no date, takes it from the byline's own ``.time-wrapper``, else from
    ``.sno-story-date`` (re-applying the ``since`` gate) and clears a
    date-only byline's bogus author/school; strips the site-name suffix so
    titles match the archive's; and sets ``id`` via ``post_id``.
    """
    record = backfill.parse_post(html, url, scraped_at, since=since, host=host)
    if record is None:
        return None
    soup = BeautifulSoup(html, "html.parser")

    if not record["published"]:
        # Scoped to the byline: other .time-wrapper elements on the page
        # belong to sidebar widgets and carry other stories' dates.
        byline_el = soup.select_one(".sno-story-byline")
        date_el = (
            byline_el.select_one(".time-wrapper") if byline_el is not None else None
        ) or soup.select_one(".sno-story-date")
        if date_el is not None:
            date_text = date_el.get_text(" ", strip=True)
            record["published"] = backfill._date_to_iso(date_text)
            if record["published"] and record["published"] < since:
                return None
            if byline_el is not None and byline_el.get_text(" ", strip=True) == date_text:
                record["author"] = record["school"] = ""  # date-only byline: no author

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

# Best of SNO republishes a winner days to weeks after the school site:
# measured 3-40 days (median 18) on 17 Carlmont winners, 2026-10-30. A
# corpus date "corroborates" a school date when it falls in this window
# after it; -1 tolerates a timezone-shifted displayed date, 60 gives margin
# over the observed maximum.
MIN_REPUBLISH_LAG_DAYS = -1
MAX_REPUBLISH_LAG_DAYS = 60

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


def _dates_corroborate(winner_published: str, record_published: str) -> bool:
    """True if the corpus (Best of SNO) date falls within the republish lag
    after the school-site date. Never compares for equality: the two dates
    differ by days to weeks for every real winner."""
    try:
        # [:10] because daily-scraper corpus rows store a full ISO datetime
        # while backfilled and school-site rows store YYYY-MM-DD.
        lag = (
            date.fromisoformat(winner_published[:10])
            - date.fromisoformat(record_published[:10])
        ).days
    except ValueError:  # an empty or malformed date corroborates nothing
        return False
    return MIN_REPUBLISH_LAG_DAYS <= lag <= MAX_REPUBLISH_LAG_DAYS


def _same_author_and_date(winner: dict, record: dict) -> bool:
    return _same_author(winner["author"], record["author"]) and _dates_corroborate(
        winner["published"], record["published"]
    )


def _uncertain(reason: str, winner: dict) -> Verdict:
    return Verdict("uncertain", winner["id"], reason, winner["title"], winner["url"])


def classify(record: dict, winners: list[dict]) -> Verdict:
    """Label ``record`` against its school's corpus winners (spec §6.4).

    ``winners`` rows carry ``id``, ``url``, ``title``, ``published``,
    ``author`` and a precomputed ``norm_title``. Rules, in order: undated ->
    uncertain; one exact normalized-title match -> winner; several -> the one
    sharing author+date, else uncertain (a single match must also fit the
    republish lag, else it is a different same-titled article, e.g. another
    installment of a recurring column -> uncertain); a near-match title ->
    uncertain; a winner sharing the author and fitting the lag under a
    different title -> uncertain; otherwise non_winner. "Date" always means
    the republish-lag window (``_dates_corroborate``), never equality. The record's own ``school`` cell is never read —
    the caller picks ``winners`` by host.
    """
    if not record["published"]:
        return Verdict("uncertain", "", "undated", "", "")

    title = normalize_title(record["title"])
    exact = [w for w in winners if w["norm_title"] == title]
    if len(exact) == 1:
        winner = exact[0]
        if _dates_corroborate(winner["published"], record["published"]):
            return Verdict("winner", winner["id"], "", "", "")
        return _uncertain("title-ambiguous", winner)
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


CHECKPOINT_EVERY = 25  # rows between checkpoint saves, matching the backfill

# The crawl window (decided 2026-10-30 from the measured 3-40 day republish
# lag). Starts Dec 1 because December school articles can be January Best of
# SNO winners; ends Sep 15 (the run date minus the 40-day max lag) so every
# included article has had time to win.
DEFAULT_SINCE = "2025-12-01"
DEFAULT_UNTIL = "2026-09-15"

# Best of SNO does not publish every day, so the first winner of a
# `--since D` backfill can be dated a few days after D.
_CORPUS_START_SLACK_DAYS = 7
_COUNT_KEYS = (
    "candidates", "winner", "non_winner", "uncertain", "skipped", "dropped_out_of_window",
)


def corpus_start(data_dir: str) -> str:
    """Earliest ``published`` date (YYYY-MM-DD) across the corpus files, any
    school; ``""`` when there is no dated winner at all."""
    return min(
        (
            row["published"][:10]
            for name in CORPUS_FILES
            for row in scraper._read_rows(os.path.join(data_dir, "data", name))
            if row.get("published")
        ),
        default="",
    )


def _require_corpus_covers(data_dir: str, since: str) -> None:
    """Refuse a crawl the winners corpus cannot label honestly.

    A school article is only labelable if every date its Best of SNO
    republish could carry is in the corpus. With no corpus, or a corpus that
    starts after ``since``, real winners would be filed as non_winner — the
    poisoned negative class (spec §4).
    """
    start = corpus_start(data_dir)
    if not start:
        raise ValueError(
            f"no winners corpus under {os.path.join(data_dir, 'data')} "
            "(archive.csv / new.csv / old.csv): run `python -m best_of_sno.backfill` first"
        )
    if date.fromisoformat(since) < date.fromisoformat(start) - timedelta(
        days=_CORPUS_START_SLACK_DAYS
    ):
        raise ValueError(
            f"--since {since} is before the winners corpus starts ({start}), so winners "
            "from that period would be labeled non_winner: run "
            f"`python -m best_of_sno.backfill --since {since}` first, or start later"
        )


def run_layer2(
    data_dir: str,
    *,
    since: str = DEFAULT_SINCE,
    until: str = DEFAULT_UNTIL,
    sites: list[str] | None = None,
    limit: int | None = None,
    delay: float = 6.0,
    dry_run: bool = False,
    fetch_sitemap=None,
    fetch_page=None,
    now: str | None = None,
) -> dict:
    """Crawl, label and write each site's in-window articles (spec §6).

    Hosts are crawled one after another, so ``delay`` between post fetches
    honors ``Crawl-delay`` per host. Done = the checkpoint UNION the ids in
    layer2.csv and uncertain.csv, so a re-run never re-fetches or duplicates
    even if the checkpoint is lost. Refuses to start when the winners
    corpus does not reach back to ``since``. A fetch failure is skipped WITHOUT
    marking done (retried next run); an out-of-window post is dropped and
    marked done. ``dry_run`` fetches sitemaps only and writes nothing.

    ``fetch_sitemap``/``fetch_page`` resolve to the backfill's network
    functions at call time, not def time, so tests of ``main`` can swap
    them. Returns ``{"sites": {host: counts}, "totals": counts}``.
    """
    backfill._require_iso_date(since, "--since")
    backfill._require_iso_date(until, "--until")
    _require_corpus_covers(data_dir, since)
    hosts = list(SITES) if sites is None else list(sites)
    unknown = [h for h in hosts if h not in SITES]
    if unknown:
        raise ValueError(f"unknown site(s): {unknown}; choose from {list(SITES)}")
    fetch_sitemap = fetch_sitemap or backfill.fetch_all_post_sitemaps
    fetch_page = fetch_page or backfill.fetch_page
    now = now or datetime.now().astimezone().isoformat()

    data = os.path.join(data_dir, "data")
    layer2_path = os.path.join(data, "layer2.csv")
    uncertain_path = os.path.join(data, "uncertain.csv")
    checkpoint_path = os.path.join(data, "layer2_state.json")

    corpus = load_winner_corpus(data_dir)
    done = (
        load_layer2_state(checkpoint_path)
        | scraper._read_ids(layer2_path)
        | scraper._read_ids(uncertain_path)
    )
    res = {"sites": {}, "totals": dict.fromkeys(_COUNT_KEYS, 0)}
    if not dry_run:
        os.makedirs(data, exist_ok=True)

    for host in hosts:
        counts = res["sites"][host] = dict.fromkeys(_COUNT_KEYS, 0)
        pairs: list[tuple[str, str]] = []
        for xml_bytes in fetch_sitemap(host=host):
            pairs.extend(backfill.parse_sitemap(xml_bytes))
        in_window = backfill.select_candidates(pairs, since)
        counts["candidates"] = len(in_window)
        if dry_run:
            LOG.info("dry-run: %s: %d candidates since %s; nothing fetched",
                     host, len(in_window), since)
            continue

        todo = [loc for loc in in_window if post_id(loc, host) not in done]
        if limit is not None:
            todo = todo[:limit]
        winners = corpus.get(SITES[host], [])
        if todo:
            time.sleep(delay)  # Crawl-delay after this host's sitemap fetches
        pending_since_save = 0
        for i, loc in enumerate(todo, start=1):
            pid = post_id(loc, host)
            if pid in done:
                continue  # loc listed twice across sub-sitemaps; already written
            try:
                html_bytes = fetch_page(loc)
            except Exception as exc:  # network/HTTP failure after retries
                LOG.warning("fetch failed, skipping (will retry next run): %s (%s)", loc, exc)
                counts["skipped"] += 1
                if i < len(todo):
                    time.sleep(delay)
                continue

            record = parse_school_post(html_bytes, loc, now, since=since, host=host)
            if record is None or (record["published"] and record["published"] > until):
                # Before since, or after until: its win status is either out
                # of scope or not yet settled, so it must not become a negative.
                counts["dropped_out_of_window"] += 1
            else:
                # On a school's own site the host IS the source, and the
                # byline's trailing segment is a staff role, not the school.
                record["source_site"] = host
                record["school"] = SITES[host]
                verdict = classify(record, winners)
                row = {**record, "label": verdict.label, "matched_id": verdict.matched_id}
                if verdict.label == "uncertain":
                    row.update(reason=verdict.reason,
                               candidate_title=verdict.candidate_title,
                               candidate_url=verdict.candidate_url)
                    append_rows(uncertain_path, [row], UNCERTAIN_COLUMNS)
                else:
                    append_rows(layer2_path, [row], LAYER2_COLUMNS)
                counts[verdict.label] += 1
            done.add(pid)
            pending_since_save += 1

            if pending_since_save >= CHECKPOINT_EVERY:
                save_layer2_state(checkpoint_path, done)
                pending_since_save = 0
            LOG.info("%s: fetched %d/%d (winner=%d non=%d uncertain=%d)",
                     host, i, len(todo), counts["winner"], counts["non_winner"],
                     counts["uncertain"])
            if i < len(todo):
                time.sleep(delay)
        save_layer2_state(checkpoint_path, done)

    for counts in res["sites"].values():
        for key in _COUNT_KEYS:
            res["totals"][key] += counts[key]
    LOG.info("layer2 done: %s", res["totals"])
    return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best of SNO Layer 2 school-site collection")
    parser.add_argument("--data-dir", default="best_of_sno", help="folder holding data/ and logs/")
    parser.add_argument("--since", default=DEFAULT_SINCE, help="ISO date; keep posts published on/after this")
    parser.add_argument("--until", default=DEFAULT_UNTIL, help="ISO date; drop posts published after this")
    parser.add_argument("--sites", default=None,
                        help=f"comma-separated hosts (default: all of {', '.join(SITES)})")
    parser.add_argument("--limit", type=int, default=None, help="cap posts fetched per site (trial runs)")
    parser.add_argument("--delay", type=float, default=6.0, help="seconds between requests (robots crawl-delay)")
    parser.add_argument("--dry-run", action="store_true", help="enumerate + report; fetch/write no posts")
    args = parser.parse_args(argv)

    sites = None
    if args.sites:
        sites = [h.strip() for h in args.sites.split(",") if h.strip()]
        unknown = [h for h in sites if h not in SITES]
        if unknown:
            parser.error(f"unknown site(s): {', '.join(unknown)}; choose from {', '.join(SITES)}")

    logs = os.path.join(args.data_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(logs, "layer2.log")),
            logging.StreamHandler(),
        ],
    )
    try:
        res = run_layer2(
            args.data_dir, since=args.since, until=args.until, sites=sites,
            limit=args.limit, delay=args.delay, dry_run=args.dry_run,
        )
    except ValueError as exc:  # a bad date or a window the corpus can't label
        parser.error(str(exc))
    LOG.info("result: %s", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
