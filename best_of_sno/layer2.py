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


# SNO's long-form ("split") story template has no .sno-story-body-content:
# the article is a run of .sno-slideshow-segment blocks (text, photo,
# quote, info box). Measured 2026-10-31: 15 of 97 matched winners used it.
_SEGMENT_NOISE = (
    "script, style, noscript, iframe, .sno-story-media-caption, "
    ".sno-story-media-photo-credit, .photo-credit, .embed-credit"
)

# An audio/video-led post: a player inside the story and almost no text.
# Real podcast show notes and video blurbs run 8-152 words; the shortest
# written article with an embedded player in the fixtures runs 530.
MEDIA_MAX_WORDS = 200
_MEDIA_HOST_RE = re.compile(
    r"youtube(-nocookie)?\.com|youtu\.be|vimeo\.com|soundcloud\.com|spotify\.com|"
    r"podbean\.com|anchor\.fm|podcasts\.apple\.com|buzzsprout\.com|libsyn\.com|"
    r"simplecast\.com|megaphone\.fm|spreaker\.com|riverside\.fm"
)


def _longform_body(soup: BeautifulSoup) -> str:
    """Text of every long-form segment in page order, minus photo captions,
    credits and embeds. Segments are collected page-wide because the
    template's loose nesting leaves only the first inside its wrapper."""
    parts = []
    for segment in soup.select(".sno-slideshow-segment"):
        for noise in segment.select(_SEGMENT_NOISE):
            noise.decompose()
        parts.append(segment.get_text(" ", strip=True))
    return scraper.strip_html(" ".join(parts))


def is_media_only(html: bytes, word_count: int) -> bool:
    """True for a podcast or video post: an audio/video player inside the
    story and fewer than ``MEDIA_MAX_WORDS`` words of text. A written story
    that embeds a player keeps its text and is not media-only."""
    if word_count >= MEDIA_MAX_WORDS:
        return False
    story = BeautifulSoup(html, "html.parser").select_one(".sno-story-wrap, .sno-story")
    if story is None:
        return False
    if story.find(["video", "audio"]) is not None:
        return True
    return any(
        _MEDIA_HOST_RE.search(frame.get("src") or frame.get("data-src") or "")
        for frame in story.find_all("iframe")
    )


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
    titles match the archive's; reads a long-form story's segments when the
    page has no standard body; and sets ``id`` via ``post_id``.
    """
    record = backfill.parse_post(html, url, scraped_at, since=since, host=host)
    if record is None:
        return None
    soup = BeautifulSoup(html, "html.parser")

    if not record["body"]:
        record["body"] = _longform_body(soup)
        record["word_count"] = scraper.word_count(record["body"])

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

# Body-text evidence (added 2026-10-31). A school article and its Best of
# SNO republish share almost all their text, so 5-word-shingle containment
# settles what titles and bylines cannot. Measured on the full crawl: the 81
# matched winners with real text on both sides overlap 0.90-0.98, the 200
# author-date look-alikes 0.01 or less, the one retitled winner 0.97.
SHINGLE_WORDS = 5
# Fewer shingles than this is no evidence: Best of SNO keeps only a 35-word
# "view this story on the original site" stub for podcast / long-form
# stories, and some school pages have no parsable body.
MIN_SHINGLES = 50
BODY_MATCH = 0.6  # at or above: the same article
BODY_MISMATCH = 0.2  # at or below: a different article
_WORD_RE = re.compile(r"\w+")


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


def text_shingles(text: str | None) -> frozenset[tuple[str, ...]]:
    """The set of overlapping ``SHINGLE_WORDS``-word runs in ``text``,
    case-folded, punctuation ignored."""
    words = _WORD_RE.findall((text or "").casefold())
    n = SHINGLE_WORDS
    return frozenset(tuple(words[i:i + n]) for i in range(len(words) - n + 1))


def body_overlap(a: frozenset, b: frozenset) -> float | None:
    """Share of the shorter text's shingles found in the other (containment,
    so a republish with an added note still scores high). ``None`` when
    either side is too short to count as evidence."""
    if len(a) < MIN_SHINGLES or len(b) < MIN_SHINGLES:
        return None
    return len(a & b) / min(len(a), len(b))


def _body_says(record_shingles: frozenset, winner: dict) -> bool | None:
    """True = same article, False = a different one, None = can't tell."""
    overlap = body_overlap(record_shingles, winner.get("shingles", frozenset()))
    if overlap is None or BODY_MISMATCH < overlap < BODY_MATCH:
        return None
    return overlap >= BODY_MATCH


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


def classify(record: dict, winners: list[dict], claimed=frozenset()) -> Verdict:
    """Label ``record`` against its school's corpus winners (spec §6.4).

    ``winners`` rows carry ``id``, ``url``, ``title``, ``published``,
    ``author``, a precomputed ``norm_title`` and body ``shingles``. Wherever
    a rule below would return uncertain for one candidate, the article bodies
    are compared first: the same text -> winner, clearly different text ->
    that candidate is ruled out, too little text -> uncertain as before.
    ``claimed`` holds corpus ids another article already matched as a
    winner; such a winner is skipped by the author-date rule only (a repost
    under the same title must still match it).
    Rules, in order: undated ->
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
    shingles = text_shingles(record.get("body"))
    ruled_out: list[dict] = []  # candidates whose body is a different article

    def remaining(ws):
        return [w for w in ws if not any(w is r for r in ruled_out)]

    def settle(candidates: list[dict], reason: str) -> Verdict | None:
        """Body-check each candidate in order: a match wins, a mismatch is
        ruled out, the first undecidable one makes the verdict uncertain."""
        unknown = None
        for w in candidates:
            says = _body_says(shingles, w)
            if says:
                return Verdict("winner", w["id"], "", "", "")
            if says is None:
                unknown = unknown or w
            else:
                ruled_out.append(w)
        return _uncertain(reason, unknown) if unknown else None

    exact = [w for w in winners if w["norm_title"] == title]
    if len(exact) == 1:
        winner = exact[0]
        if _dates_corroborate(winner["published"], record["published"]):
            return Verdict("winner", winner["id"], "", "", "")
        verdict = settle(exact, "title-ambiguous")
        if verdict:
            return verdict
    elif exact:
        corroborated = [w for w in exact if _same_author_and_date(w, record)]
        if len(corroborated) == 1:
            return Verdict("winner", corroborated[0]["id"], "", "", "")
        return _uncertain("title-ambiguous", exact[0])

    scored = [(difflib.SequenceMatcher(None, title, w["norm_title"]).ratio(), w)
              for w in remaining(winners)]
    near = [w for ratio, w in sorted(scored, key=lambda p: -p[0]) if ratio >= NEARMATCH_RATIO]
    verdict = settle(near, "title-nearmatch")
    if verdict:
        return verdict

    same_writer = [w for w in remaining(winners)
                   if w["id"] not in claimed and _same_author_and_date(w, record)]
    verdict = settle(same_writer, "author-date")
    if verdict:
        return verdict
    return Verdict("non_winner", "", "", "", "")


def load_winner_corpus(data_dir: str) -> dict[str, list[dict]]:
    """Index the winners corpus (archive ∪ new ∪ old) by school name.

    Keeps only the schools in ``SITES`` and projects each row to the lookup
    fields plus a precomputed ``norm_title`` and body ``shingles``; the body
    text itself is dropped so it is not held through a multi-hour crawl.
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
            winner["shingles"] = text_shingles(row.get("body"))
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
    "dropped_media",
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
            elif is_media_only(html_bytes, record["word_count"]):
                # A podcast or video: almost no text to learn from or judge.
                counts["dropped_media"] += 1
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


def relabel_uncertain(data_dir: str) -> dict:
    """Re-judge every row of uncertain.csv against the corpus, offline.

    Winners already matched in layer2.csv are passed to ``classify`` as
    ``claimed``. Rows the current ``classify`` now settles move to layer2.csv; the rest
    stay, with their reason and candidate refreshed. Nothing is fetched: the
    stored title, byline, date and body are the evidence. layer2.csv is
    written before uncertain.csv, and ids already in layer2.csv are not
    appended again, so a crash between the two writes is repaired by
    re-running. Returns how many rows got each label.
    """
    data = os.path.join(data_dir, "data")
    layer2_path = os.path.join(data, "layer2.csv")
    uncertain_path = os.path.join(data, "uncertain.csv")
    counts = {"winner": 0, "non_winner": 0, "uncertain": 0}
    rows = scraper._read_rows(uncertain_path)
    if not rows:
        return counts

    corpus = load_winner_corpus(data_dir)
    labeled = scraper._read_rows(layer2_path)
    have = {row["id"] for row in labeled}
    claimed = {row["matched_id"] for row in labeled if row.get("label") == "winner"}
    moved, kept = [], []
    for row in rows:
        school = SITES.get(row.get("source_site", ""), row.get("school", ""))
        verdict = classify(row, corpus.get(school, []), claimed)
        counts[verdict.label] += 1
        if verdict.label == "winner":
            claimed.add(verdict.matched_id)
        if verdict.label == "uncertain":
            row.update(matched_id=verdict.matched_id, reason=verdict.reason,
                       candidate_title=verdict.candidate_title,
                       candidate_url=verdict.candidate_url)
            kept.append(row)
        elif row["id"] not in have:
            have.add(row["id"])
            moved.append({**row, "label": verdict.label, "matched_id": verdict.matched_id})

    if moved:
        scraper._atomic_write_text(layer2_path, _rows_to_csv_text(labeled + moved, LAYER2_COLUMNS))
    scraper._atomic_write_text(uncertain_path, _rows_to_csv_text(kept, UNCERTAIN_COLUMNS))
    LOG.info("relabel: %s", counts)
    return counts


def forget_thin(data_dir: str, sites: list[str] | None = None,
                max_words: int = MEDIA_MAX_WORDS) -> int:
    """Remove rows under ``max_words`` words (for ``sites``, default all)
    from layer2.csv, uncertain.csv and the checkpoint, so the next crawl
    re-fetches them with the current parser. Returns how many were removed.

    The rows are written out of the CSVs before the checkpoint forgets
    them; either way a crash leaves them not-done, so a crawl re-fetches.
    """
    data = os.path.join(data_dir, "data")
    hosts = set(SITES if sites is None else sites)
    forgotten: set[str] = set()
    for name, columns in (("layer2.csv", LAYER2_COLUMNS), ("uncertain.csv", UNCERTAIN_COLUMNS)):
        path = os.path.join(data, name)
        rows = scraper._read_rows(path)
        keep = []
        for row in rows:
            if row.get("source_site") in hosts and int(row.get("word_count") or 0) < max_words:
                forgotten.add(row["id"])
            else:
                keep.append(row)
        if len(keep) != len(rows):
            scraper._atomic_write_text(path, _rows_to_csv_text(keep, columns))
    checkpoint = os.path.join(data, "layer2_state.json")
    done = load_layer2_state(checkpoint)
    if done & forgotten:
        save_layer2_state(checkpoint, done - forgotten)
    LOG.info("forgot %d thin rows for re-fetch", len(forgotten))
    return len(forgotten)


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
    parser.add_argument("--refetch-thin", action="store_true",
                        help=f"re-fetch rows under {MEDIA_MAX_WORDS} words with the current parser")
    parser.add_argument("--relabel", action="store_true",
                        help="re-judge uncertain.csv against the corpus offline; fetch nothing")
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
    if args.relabel:
        LOG.info("result: %s", relabel_uncertain(args.data_dir))
        return 0
    try:
        if args.refetch_thin:
            forget_thin(args.data_dir, sites)
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
