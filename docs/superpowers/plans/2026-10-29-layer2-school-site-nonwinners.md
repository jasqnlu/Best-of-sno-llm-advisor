# Layer 2 School-Site Non-Winner Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect every article published 2026-01-01 → 2026-10-10 on five SNO-platform high-school news sites, auto-label each `winner` / `non_winner` / `uncertain` by cross-referencing the Layer 1 winners corpus, and write them to `layer2.csv` + `uncertain.csv` as Layer 4's training data.

**Architecture:** New module `best_of_sno/layer2.py`. Sitemap enumeration, polite fetching, and post-HTML parsing are **imported from `best_of_sno/backfill.py`** after a behavior-preserving refactor that gives three helpers an optional `host` parameter. What is genuinely new lives in `layer2.py`: the host→school table, the winners-corpus index, the title-match labeler, a wider-column writer, and the per-host crawl loop.

**Tech Stack:** Python 3.14; `requests`, `beautifulsoup4`, `defusedxml` (all already installed). Similarity via stdlib `difflib`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-29-layer2-school-site-nonwinners-design.md`

## Global Constraints

- **Python 3.14**; no new dependencies.
- **Reuse, do not reimplement.** From `scraper.py`: `COLUMNS`, `USER_AGENT`,
  `parse_byline`, `strip_html`, `word_count`, `_csv_safe`, `_read_rows`,
  `_read_ids`, `_atomic_write_text`. From `backfill.py`: `parse_sitemap`,
  `select_candidates`, `post_id_from_url`, `parse_post`, `fetch_page`,
  `fetch_all_post_sitemaps`. Import them.
- **`backfill.py` and `scraper.py` behavior is unchanged.** Every refactor in
  Task 1 is parameter-adding with a default that reproduces today's behavior
  exactly. **The backfill's 53 existing tests must pass unchanged, with no
  edits to any existing test file**, and `archive.csv` output stays
  byte-for-byte identical.
- **Winner corpus = `archive.csv` ∪ `new.csv` ∪ `old.csv`**, never
  `archive.csv` alone. Each winner lives in exactly one of the three by
  design (`run_backfill` skips ids already in `new`/`old`), so matching only
  the archive would mislabel a daily-caught winner as a non-winner.
- **Schema parity:** `layer2.csv` is `scraper.COLUMNS` in that exact order,
  then `label`, `matched_id`. The 12 archive columns are never renamed,
  reordered, or substituted — Layers 3–4 read `archive.csv` and `layer2.csv`
  as one corpus.
- **CSV dialect = `QUOTE_MINIMAL`** (csv's default), matching the shipped
  `archive.csv`. Every cell passes through `scraper._csv_safe`.
- **robots.txt (identical on all five hosts):** no URL containing `?` is ever
  fetched; `Crawl-delay: 6` → default 6.0s between requests **per host**,
  injectable for tests; always send `scraper.USER_AGENT`.
- **Date window:** `--since` default `2026-01-01`, `--until` default
  `2026-10-10`. Both must be zero-padded ISO (`YYYY-MM-DD`) — dates are
  compared lexically, so a non-padded value would silently mis-filter.
- **Undated articles** (`published == ""`) go to `uncertain.csv` with
  `reason="undated"`. They are never written to `layer2.csv` and never
  silently discarded.
- **Outputs, all git-ignored:** `best_of_sno/data/layer2.csv`,
  `best_of_sno/data/uncertain.csv`, `best_of_sno/data/layer2_state.json`.
- **The five sites** (host → school name as it appears in the corpus):
  `scotscoop.com` → `Carlmont High School`;
  `elestoque.org` → `Monta Vista High School`;
  `torreypinesfalconer.com` → `Torrey Pines High School`;
  `theburlingameb.org` → `Burlingame High School`;
  `harkeraquila.com` → `The Harker School`.
  (Verified against the shipped `archive.csv` 2026-10-29: 61 / 14 / 9 / 9 / 7
  winners = 100 total, of which 94 fall on or before 2026-10-10.)

## Review Focus

- **A winner that lives only in `new.csv` or `old.csv`** must label as
  `winner`, not `non_winner` — the poisoned-negative anti-goal (spec §4).
  *(Test in Task 4.)*
- **An undated article** (missing or unparseable `.sno-story-byline`) must
  land in `uncertain.csv` with `reason="undated"`, never in the negative
  class, and never be dropped. *(Test in Task 3, end-to-end in Task 6.)*
- **The same numeric post id on two different hosts** (`scotscoop.com/?p=50`
  and `elestoque.org/?p=50`) must produce two distinct rows and two distinct
  checkpoint ids — a collision would silently discard one site's article.
  *(Test in Task 6.)*
- **`published` format mismatch across corpus files:** backfilled rows carry
  `2026-01-05` while daily-scraper rows carry `2026-10-28T16:08:34+00:00`.
  The author+date corroboration rule must compare `published[:10]` or it will
  look implemented and never fire for a daily-caught winner.
  *(Test in Task 3.)*
- **Fetch failure or interrupt in a ~6.7-hour run:** one failing URL must be
  logged and skipped **without** being marked done (so a re-run retries it),
  the run must continue, and a resumed run must re-fetch nothing and write no
  duplicate row. *(Test in Task 6.)*

---

### Task 1: Host-parameterize the backfill helpers (behavior-preserving)

**Files:**
- Modify: `best_of_sno/backfill.py`
- Test: `best_of_sno/tests/test_layer2_hosts.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces (all defaults reproduce today's behavior exactly):
  - `sitemap_index_url(host: str) -> str` — `f"https://{host}/wp-sitemap.xml"`.
    `SITEMAP_INDEX` stays as a module constant, now `sitemap_index_url("bestofsno.com")`.
  - `post_id_from_url(url: str, *, host: str = "bestofsno.com") -> str` —
    `f"https://{host}/?p=<1st path segment>"`.
  - `parse_post(html, url, scraped_at, *, since, host: str = "bestofsno.com") -> dict | None`
    — threads `host` into its `post_id_from_url` call; nothing else changes.
  - `fetch_all_post_sitemaps(*, session=None, host: str = "bestofsno.com", delay: float = 6.0) -> list[bytes]`
    — uses `sitemap_index_url(host)`; sleeps `delay` (not a literal `6`)
    between sub-sitemap fetches.
  - `_require_iso_date(value: str, flag: str) -> str` — extracted verbatim
    from `run_backfill`'s inline validation; raises `ValueError` with
    `f"{flag} must be an ISO date (YYYY-MM-DD): {value!r}"` or
    `f"{flag} must be zero-padded (YYYY-MM-DD): {value!r}"`. `run_backfill`
    now calls `_require_iso_date(since, "--since")`, so its messages and
    raised type are unchanged.
- **Must NOT change:** `run_backfill`'s own signature or its
  `fetch_sitemap()` call (existing tests inject a zero-argument fake).

- [ ] **Step 1: Write the failing tests** in `best_of_sno/tests/test_layer2_hosts.py`

```python
import pytest
from best_of_sno.backfill import (
    SITEMAP_INDEX, sitemap_index_url, post_id_from_url, parse_post, _require_iso_date,
)

POST = b"""<html><head><meta property='og:title' content='A Story'></head>
<body><span class='sno-story-byline'>By Ada Lee, Carlmont High School \xe2\x80\xa2 March 3, 2026</span>
<div class='sno-story-body-content'><p>Body words here.</p></div></body></html>"""

def test_sitemap_index_url_per_host_and_default_constant_unchanged():
    assert sitemap_index_url("elestoque.org") == "https://elestoque.org/wp-sitemap.xml"
    assert SITEMAP_INDEX == "https://bestofsno.com/wp-sitemap.xml"

def test_post_id_default_host_is_bestofsno():
    assert (post_id_from_url("https://bestofsno.com/89942/arts/scene-around/")
            == "https://bestofsno.com/?p=89942")

def test_post_id_honors_host_so_ids_never_collide_across_sites():
    assert (post_id_from_url("https://scotscoop.com/50/news/x/", host="scotscoop.com")
            == "https://scotscoop.com/?p=50")
    assert (post_id_from_url("https://elestoque.org/50/news/x/", host="elestoque.org")
            == "https://elestoque.org/?p=50")

def test_parse_post_threads_host_into_id():
    r = parse_post(POST, "https://scotscoop.com/50/news/x/", "NOW",
                   since="2026-01-01", host="scotscoop.com")
    assert r["id"] == "https://scotscoop.com/?p=50"
    assert r["published"] == "2026-03-03" and r["author"] == "Ada Lee"

def test_parse_post_default_host_unchanged():
    r = parse_post(POST, "https://bestofsno.com/50/news/x/", "NOW", since="2026-01-01")
    assert r["id"] == "https://bestofsno.com/?p=50"

@pytest.mark.parametrize("bad", ["2026-1-1", "nope", "", "2026/01/01"])
def test_require_iso_date_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        _require_iso_date(bad, "--until")

def test_require_iso_date_returns_good_value():
    assert _require_iso_date("2026-10-10", "--until") == "2026-10-10"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_hosts.py -v`
Expected: FAIL — `ImportError` on `sitemap_index_url` / `_require_iso_date`.

- [ ] **Step 3: Apply the four parameter additions and the one extraction** in `best_of_sno/backfill.py`

Add `host`/`delay` keyword-only parameters with the defaults above; replace
`run_backfill`'s inline `strptime`/round-trip block with a call to
`_require_iso_date(since, "--since")`, moving that exact logic into the new
function. Keep every docstring accurate.

- [ ] **Step 4: Run the new tests AND the whole existing suite, verify all pass**

Run: `.venv/bin/python -m pytest best_of_sno/tests -v`
Expected: PASS — the 53 pre-existing tests plus the 7 new ones, **with no
existing test file edited**. If any pre-existing test needed a change, the
refactor was not behavior-preserving: revert and re-do it.

- [ ] **Step 5: Commit**

```bash
git add best_of_sno/backfill.py best_of_sno/tests/test_layer2_hosts.py
git commit -m "refactor: backfill helpers take an optional host"
```

---

### Task 2: Real fixtures from all five sites + parser-drift proof

The spec's §10 open risk is parser drift across the five sites. This task
proves the shipped parser handles all five **before** a 6.7-hour crawl runs.

**Files:**
- Create: `best_of_sno/tests/fixtures/layer2/<slug>_post.html` ×5 and
  `best_of_sno/tests/fixtures/layer2/<slug>_sitemap.xml` ×5, where `<slug>` is
  `scotscoop`, `elestoque`, `torreypinesfalconer`, `theburlingameb`, `harkeraquila`
- Create: `best_of_sno/tests/test_layer2_parse_sites.py`

**Interfaces:**
- Consumes: `backfill.parse_post` with `host=` (Task 1), `backfill.parse_sitemap`,
  `backfill.sitemap_index_url`, `scraper.fetch_feed`.
- Produces: the fixture files every later task's tests read.

- [ ] **Step 1: Capture the fixtures from the live sites, politely**

Write a throwaway capture script **in the scratchpad, not in the repo**. For
each of the five hosts it must: GET `sitemap_index_url(host)`, GET the first
`wp-sitemap-posts-post-*.xml`, pick one `<loc>` whose `<lastmod>` is in
2026, GET that post page — all through `scraper.fetch_feed` (so the contact
User-Agent is sent), **`time.sleep(6)` between every request**, and never
build a URL containing `?`. Save the post HTML verbatim as
`<slug>_post.html`. Save the sub-sitemap trimmed to exactly 3 `<url>`
entries — two with a 2026 `lastmod` (one of them the captured post) and one
with a 2025 `lastmod` — as `<slug>_sitemap.xml`, mirroring
`fixtures/backfill/sitemap_sample.xml`.

- [ ] **Step 2: Write the failing test** in `best_of_sno/tests/test_layer2_parse_sites.py`

```python
import re
from pathlib import Path
import pytest
from best_of_sno.backfill import parse_post, parse_sitemap, select_candidates
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
    r = parse_post((FX / f"{slug}_post.html").read_bytes(), locs[0], "NOW",
                   since="2026-01-01", host=host)
    assert r is not None, f"{host}: parse_post dropped an in-window post"
    assert set(r) == set(COLUMNS)
    assert r["id"].startswith(f"https://{host}/?p=")
    assert r["title"].strip(), f"{host}: no og:title"
    assert r["word_count"] > 50, f"{host}: body too short — selector drift"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["published"]), f"{host}: byline date unparsed"
    assert r["author"].strip(), f"{host}: byline author unparsed"

@pytest.mark.parametrize("slug,host", SITES)
def test_every_site_sitemap_url_is_query_free(slug, host):
    for loc, _ in parse_sitemap((FX / f"{slug}_sitemap.xml").read_bytes()):
        assert "?" not in loc  # robots.txt disallows any ?-bearing URL
```

- [ ] **Step 3: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_parse_sites.py -v`
Expected: FAIL before the fixtures exist (`FileNotFoundError`).

- [ ] **Step 4: Run the tests against the captured fixtures, verify they pass**

Expected: PASS for all five hosts. **A failure here is a real finding, not a
test to loosen** — it means that site's markup differs and `parse_post` needs
a per-site fallback. Stop and report it rather than weakening the assertion.

- [ ] **Step 5: Commit**

```bash
git add best_of_sno/tests/fixtures/layer2 best_of_sno/tests/test_layer2_parse_sites.py
git commit -m "test: prove the post parser handles all five school sites"
```

---

### Task 3: Title normalization + the three-way labeler

**Files:**
- Create: `best_of_sno/layer2.py` (module scaffold + these names)
- Test: `best_of_sno/tests/test_layer2_label.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2 (pure logic).
- Produces:
  - `NEARMATCH_RATIO = 0.90` — `difflib.SequenceMatcher` ratio at or above
    which two normalized titles are a near-match. **Pinned empirically:**
    across all 2,014 intra-school pairs of real `archive.csv` winner titles,
    the closest pair of *distinct* titles scores 0.849 ("The art of
    preservation: Fanmaking" vs "…: Glass eye making"), so 0.90 clears every
    real negative while 0.85 would not.
  - `normalize_title(title: str | None) -> str` — `html.unescape`, then every
    Unicode punctuation character (category starting `P`) replaced by a
    space, then whitespace collapsed, then lowercased. Replacing punctuation
    with a space rather than deleting it keeps `"art—the"` from becoming one
    word; `"don't"` and `"don’t"` both become `"don t"`, so they still match.
  - `class Verdict(NamedTuple)` with fields
    `label: str`, `matched_id: str`, `reason: str`, `candidate_title: str`,
    `candidate_url: str`. `label` ∈ `{"winner", "non_winner", "uncertain"}`;
    `reason` is `""` for confident rows, else one of
    `"undated"`, `"title-nearmatch"`, `"author-date"`, `"title-ambiguous"`.
  - `classify(record: dict, winners: list[dict]) -> Verdict` — `winners` are
    the corpus rows for this host's school (Task 4), each carrying
    `id`, `url`, `title`, `published`, `author`, `norm_title`.

  **Decision rules, in this order:**
  1. `record["published"] == ""` → `Verdict("uncertain", "", "undated", "", "")`.
  2. Exactly one winner with `norm_title == normalize_title(record["title"])`
     → `Verdict("winner", w["id"], "", "", "")`.
  3. More than one such winner → narrow to those whose `author` equals
     `record["author"]` **and** whose `published[:10]` equals
     `record["published"][:10]`; exactly one survivor → `winner`; otherwise
     → `uncertain` / `"title-ambiguous"` carrying the first candidate.
  4. No exact match, but some winner's `norm_title` scores
     `>= NEARMATCH_RATIO` → `uncertain` / `"title-nearmatch"` with the
     highest-scoring candidate.
  5. Still no match, but some winner has a non-empty `author` equal to
     `record["author"]` **and** `published[:10]` equal to
     `record["published"][:10]` → `uncertain` / `"author-date"`.
     **The `[:10]` slice is required:** backfilled corpus rows store
     `"2026-01-05"` while daily-scraper rows store
     `"2026-10-28T16:08:34+00:00"`.
  6. Otherwise → `Verdict("non_winner", "", "", "", "")`.

  *Note on the `reason` vocabulary:* spec §7 names only `title-nearmatch`
  and `undated`, but §8 requires the same-title and author-corroboration
  cases to reach `uncertain` too. Rather than mislabel them
  `title-nearmatch`, they get their own honest values — `author-date` and
  `title-ambiguous` — which is a deliberate widening of §7's list, not drift.

- [ ] **Step 1: Write the failing tests** in `best_of_sno/tests/test_layer2_label.py`

```python
from best_of_sno.layer2 import classify, normalize_title, NEARMATCH_RATIO

def _w(title, **kw):
    w = {"id": "https://bestofsno.com/?p=1", "url": "https://bestofsno.com/1/a/b/",
         "title": title, "published": "2026-03-03", "author": "Ada Lee"}
    w.update(kw)
    w["norm_title"] = normalize_title(w["title"])
    return w

def _r(title, published="2026-03-03", author="Ada Lee"):
    return {"title": title, "published": published, "author": author}

def test_normalize_title_folds_case_entities_and_smart_quotes():
    assert normalize_title("Don&#8217;t Look Away!") == normalize_title("don’t look away")
    assert normalize_title("  A  B ") == "a b"

def test_normalize_title_does_not_weld_words_across_punctuation():
    assert normalize_title("art—the end") == "art the end"

def test_exact_normalized_match_is_a_winner():
    v = classify(_r("Don’t Look Away"), [_w("Don&#8217;t look away!")])
    assert v.label == "winner" and v.matched_id == "https://bestofsno.com/?p=1"
    assert v.reason == ""

def test_no_match_is_a_non_winner():
    v = classify(_r("A completely unrelated headline"), [_w("Don’t Look Away")])
    assert v.label == "non_winner" and v.matched_id == "" and v.reason == ""

def test_undated_is_uncertain_even_when_the_title_matches_exactly():
    v = classify(_r("Don’t Look Away", published=""), [_w("Don’t Look Away")])
    assert v.label == "uncertain" and v.reason == "undated"

def test_near_match_is_uncertain_with_candidate_fields():
    v = classify(_r("The art of preservation: Fanmakingg"),
                 [_w("The art of preservation: Fanmaking")])
    assert v.label == "uncertain" and v.reason == "title-nearmatch"
    assert v.candidate_title == "The art of preservation: Fanmaking"
    assert v.candidate_url.startswith("https://bestofsno.com/")

def test_real_0849_pair_stays_a_non_winner():
    # Two genuinely different Carlmont winners score 0.849 — the threshold
    # must sit above that, or every sibling article floods uncertain.csv.
    v = classify(_r("The art of preservation: Glass eye making", author="May Lin",
                    published="2026-01-06"),
                 [_w("The art of preservation: Fanmaking", author="May Lin",
                     published="2026-01-05")])
    assert v.label == "non_winner", f"threshold {NEARMATCH_RATIO} is too low"

def test_same_author_and_date_with_a_different_title_is_uncertain():
    v = classify(_r("An unrelated same-day story"), [_w("Don’t Look Away")])
    assert v.label == "uncertain" and v.reason == "author-date"

def test_author_date_rule_fires_across_corpus_date_formats():
    # A daily-scraper row stores a full ISO datetime; a school-site row
    # stores YYYY-MM-DD. Comparison must be on published[:10].
    v = classify(_r("An unrelated same-day story", published="2026-10-28"),
                 [_w("Don’t Look Away", published="2026-10-28T16:08:34+00:00")])
    assert v.label == "uncertain" and v.reason == "author-date"

def test_labeling_ignores_the_rows_own_school_cell():
    # A multi-author byline ("By A, B, and C") makes parse_byline return an
    # empty school (spec §8). Labeling uses the host->school map, so an empty
    # or wrong school cell on the record must not stop an exact title match.
    r = _r("Don’t Look Away")
    r["school"] = ""
    v = classify(r, [_w("Don’t Look Away")])
    assert v.label == "winner"

def test_duplicate_title_disambiguated_by_author_and_date():
    winners = [_w("Same Title", id="A", author="Ada Lee", published="2026-03-03"),
               _w("Same Title", id="B", author="Bo Chen", published="2026-05-05")]
    v = classify(_r("Same Title", author="Bo Chen", published="2026-05-05"), winners)
    assert v.label == "winner" and v.matched_id == "B"

def test_duplicate_title_that_cannot_be_disambiguated_is_uncertain():
    winners = [_w("Same Title", id="A", author="Ada Lee", published="2026-03-03"),
               _w("Same Title", id="B", author="Ada Lee", published="2026-03-03")]
    v = classify(_r("Same Title", author="Zed Zhu", published="2026-09-09"), winners)
    assert v.label == "uncertain" and v.reason == "title-ambiguous"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_label.py -v`
Expected: FAIL — `best_of_sno.layer2` does not exist.

- [ ] **Step 3: Create `best_of_sno/layer2.py`** with a module docstring citing
the spec path and `from . import backfill, scraper` (module-qualified, so
Layer 2's own `append_rows` in Task 5 can never be confused with
`backfill.append_rows`), then implement `NEARMATCH_RATIO`, `normalize_title`,
`Verdict`, and `classify` per the rules above. Use `unicodedata.category`
for the punctuation test and `difflib.SequenceMatcher(None, a, b).ratio()`
for similarity.

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_label.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add best_of_sno/layer2.py best_of_sno/tests/test_layer2_label.py
git commit -m "feat: layer2 title normalization + three-way labeler"
```

---

### Task 4: Site table + winners-corpus index

**Files:**
- Modify: `best_of_sno/layer2.py`
- Test: `best_of_sno/tests/test_layer2_corpus.py`

**Interfaces:**
- Consumes: `normalize_title` (Task 3), `scraper._read_rows`.
- Produces:
  - `SITES: dict[str, str]` — the five host → school-name entries from
    Global Constraints, in that order.
  - `CORPUS_FILES = ("archive.csv", "new.csv", "old.csv")`.
  - `load_winner_corpus(data_dir: str) -> dict[str, list[dict]]` — reads
    `<data_dir>/data/<each of CORPUS_FILES>` that exist, keeps only rows whose
    `school` is one of `SITES.values()`, and returns them grouped by school
    name. Each returned row is **projected** to `id`, `url`, `title`,
    `published`, `author` plus a precomputed `norm_title` — the `body` column
    is dropped, which keeps the 11 MB archive from being held in memory
    during a multi-hour crawl. A school with no winners maps to `[]` or is
    absent; callers use `corpus.get(school, [])`.

- [ ] **Step 1: Write the failing tests** in `best_of_sno/tests/test_layer2_corpus.py`

```python
import csv
from best_of_sno.layer2 import SITES, load_winner_corpus, normalize_title
from best_of_sno.scraper import COLUMNS

def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval="")
        w.writeheader()
        w.writerows(rows)

def _row(id_, title, school, **kw):
    r = {c: "" for c in COLUMNS}
    r.update(id=id_, title=title, school=school, published="2026-03-03",
             author="Ada Lee", url="https://bestofsno.com/1/a/b/", body="x " * 200)
    r.update(kw)
    return r

def test_sites_table_has_the_five_hosts_and_school_names():
    assert SITES == {
        "scotscoop.com": "Carlmont High School",
        "elestoque.org": "Monta Vista High School",
        "torreypinesfalconer.com": "Torrey Pines High School",
        "theburlingameb.org": "Burlingame High School",
        "harkeraquila.com": "The Harker School",
    }

def test_corpus_unions_all_three_winner_files(tmp_path):
    d = tmp_path / "data"
    _write(d / "archive.csv", [_row("A", "Archive Story", "Carlmont High School")])
    _write(d / "new.csv", [_row("N", "New Story", "Carlmont High School")])
    _write(d / "old.csv", [_row("O", "Old Story", "Monta Vista High School")])
    corpus = load_winner_corpus(str(tmp_path))
    assert {w["id"] for w in corpus["Carlmont High School"]} == {"A", "N"}
    assert {w["id"] for w in corpus["Monta Vista High School"]} == {"O"}

def test_a_winner_only_in_new_csv_is_in_the_corpus(tmp_path):
    # The poisoned-negative guard: run_backfill keeps daily-caught winners OUT
    # of archive.csv, so archive-only matching would mislabel them non_winner.
    d = tmp_path / "data"
    _write(d / "archive.csv", [_row("A", "Archive Story", "Carlmont High School")])
    _write(d / "new.csv", [_row("N", "Daily Caught Winner", "Carlmont High School")])
    titles = {w["norm_title"] for w in load_winner_corpus(str(tmp_path))["Carlmont High School"]}
    assert normalize_title("Daily Caught Winner") in titles

def test_missing_corpus_files_are_harmless(tmp_path):
    d = tmp_path / "data"
    _write(d / "archive.csv", [_row("A", "Only Archive", "Carlmont High School")])
    corpus = load_winner_corpus(str(tmp_path))  # no new.csv, no old.csv
    assert len(corpus["Carlmont High School"]) == 1

def test_corpus_is_empty_when_no_files_exist(tmp_path):
    assert load_winner_corpus(str(tmp_path)) == {}

def test_corpus_drops_body_and_precomputes_norm_title(tmp_path):
    _write(tmp_path / "data" / "archive.csv",
           [_row("A", "Don’t Look Away", "Carlmont High School")])
    w = load_winner_corpus(str(tmp_path))["Carlmont High School"][0]
    assert set(w) == {"id", "url", "title", "published", "author", "norm_title"}
    assert w["norm_title"] == normalize_title("Don’t Look Away")

def test_corpus_excludes_schools_we_do_not_crawl(tmp_path):
    _write(tmp_path / "data" / "archive.csv",
           [_row("A", "Elsewhere", "Harvard-Westlake School")])
    assert load_winner_corpus(str(tmp_path)) == {}
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_corpus.py -v`
Expected: FAIL — `SITES` / `load_winner_corpus` not defined.

- [ ] **Step 3: Implement `SITES`, `CORPUS_FILES`, and `load_winner_corpus`** in
`best_of_sno/layer2.py`. Read each file with `scraper._read_rows` (which
already returns `[]` for a missing file).

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_corpus.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add best_of_sno/layer2.py best_of_sno/tests/test_layer2_corpus.py
git commit -m "feat: layer2 site table + winners corpus from archive/new/old"
```

---

### Task 5: Wide-column writers + resume checkpoint

`backfill.append_rows` is hardwired to the 12 `scraper.COLUMNS` with
`extrasaction="ignore"`, so reusing it would **silently drop** `label`,
`matched_id`, `reason`, and the candidate fields. Layer 2 needs its own
writer bound to its own column lists.

**Files:**
- Modify: `best_of_sno/layer2.py`, `.gitignore`
- Test: `best_of_sno/tests/test_layer2_io.py`

**Interfaces:**
- Consumes: `scraper.COLUMNS`, `scraper._csv_safe`, `scraper._read_rows`,
  `scraper._atomic_write_text`.
- Produces:
  - `LAYER2_COLUMNS = scraper.COLUMNS + ["label", "matched_id"]` (14).
  - `UNCERTAIN_COLUMNS = LAYER2_COLUMNS + ["reason", "candidate_title", "candidate_url"]` (17).
  - `_rows_to_csv_text(records: list[dict], columns: list[str]) -> str` —
    `csv.DictWriter` with `restval=""`, `extrasaction="ignore"`, default
    `QUOTE_MINIMAL`, every cell through `scraper._csv_safe`; header first.
  - `append_rows(path: str, records: list[dict], columns: list[str]) -> None` —
    read-existing + atomic full rewrite (the backfill's crash-safe pattern,
    not `open("a")`), so an interrupt never leaves a half-written row and the
    file always has exactly one header. No-op on an empty `records`.
  - `load_layer2_state(path: str) -> set[str]` — `done_ids`; missing or
    corrupt file → `set()`.
  - `save_layer2_state(path: str, done_ids: set[str]) -> None` — atomic JSON,
    `done_ids` sorted.
- Also: add `best_of_sno/data/layer2_state.json` to `.gitignore`
  (`best_of_sno/data/*.csv` already covers both output CSVs).

- [ ] **Step 1: Write the failing tests** in `best_of_sno/tests/test_layer2_io.py`

```python
import csv
from best_of_sno.layer2 import (
    LAYER2_COLUMNS, UNCERTAIN_COLUMNS, append_rows,
    load_layer2_state, save_layer2_state,
)

def _rec(id_, columns, **kw):
    r = {c: "" for c in columns}
    r["id"] = id_
    r.update(kw)
    return r

def _rows(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def test_column_lists_extend_the_archive_schema():
    from best_of_sno.scraper import COLUMNS
    assert LAYER2_COLUMNS[:len(COLUMNS)] == COLUMNS
    assert LAYER2_COLUMNS[len(COLUMNS):] == ["label", "matched_id"]
    assert UNCERTAIN_COLUMNS[len(LAYER2_COLUMNS):] == [
        "reason", "candidate_title", "candidate_url"]

def test_append_writes_one_header_then_appends(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [_rec("a", LAYER2_COLUMNS, label="winner")], LAYER2_COLUMNS)
    append_rows(p, [_rec("b", LAYER2_COLUMNS, label="non_winner")], LAYER2_COLUMNS)
    rows = _rows(p)
    assert [r["id"] for r in rows] == ["a", "b"]
    assert [r["label"] for r in rows] == ["winner", "non_winner"]
    assert open(p, encoding="utf-8").read().count("id,url,title") == 1

def test_append_keeps_the_uncertain_columns(tmp_path):
    p = str(tmp_path / "uncertain.csv")
    append_rows(p, [_rec("u", UNCERTAIN_COLUMNS, label="uncertain",
                         reason="undated", candidate_title="T",
                         candidate_url="U")], UNCERTAIN_COLUMNS)
    r = _rows(p)[0]
    assert r["reason"] == "undated" and r["candidate_title"] == "T" and r["candidate_url"] == "U"

def test_append_is_a_noop_for_no_records(tmp_path):
    p = tmp_path / "layer2.csv"
    append_rows(str(p), [], LAYER2_COLUMNS)
    assert not p.exists()

def test_append_neutralizes_formula_injection(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [_rec("x", LAYER2_COLUMNS, title="=cmd()")], LAYER2_COLUMNS)
    assert _rows(p)[0]["title"].startswith("'")

def test_dialect_is_quote_minimal_like_the_archive(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [_rec("x", LAYER2_COLUMNS, title="A, B", summary="plain")],
                LAYER2_COLUMNS)
    text = open(p, encoding="utf-8").read()
    assert '"A, B"' in text        # a comma forces quoting
    assert '"plain"' not in text   # nothing else is quoted

def test_extra_keys_are_dropped_and_missing_keys_blank(tmp_path):
    p = str(tmp_path / "layer2.csv")
    append_rows(p, [{"id": "x", "bogus": "drop me"}], LAYER2_COLUMNS)
    r = _rows(p)[0]
    assert "bogus" not in r and r["title"] == "" and r["label"] == ""

def test_state_roundtrip_and_corrupt_fallback(tmp_path):
    sp = str(tmp_path / "layer2_state.json")
    assert load_layer2_state(sp) == set()
    save_layer2_state(sp, {"https://scotscoop.com/?p=1"})
    assert load_layer2_state(sp) == {"https://scotscoop.com/?p=1"}
    open(sp, "w").write("{bad json")
    assert load_layer2_state(sp) == set()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_io.py -v`
Expected: FAIL — the writer and state functions are not defined.

- [ ] **Step 3: Implement the two column lists, `_rows_to_csv_text`,
`append_rows`, `load_layer2_state`, `save_layer2_state`**, and add the
`.gitignore` line.

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_io.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add best_of_sno/layer2.py best_of_sno/tests/test_layer2_io.py .gitignore
git commit -m "feat: layer2 wide-column writers + resume checkpoint"
```

---

### Task 6: Per-host crawl orchestration + CLI

**Files:**
- Modify: `best_of_sno/layer2.py`
- Test: `best_of_sno/tests/test_layer2_run.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `CHECKPOINT_EVERY = 25` — rows between checkpoint saves, matching the backfill.
  - ```
    run_layer2(data_dir: str, *, since: str = "2026-01-01",
               until: str = "2026-10-10", sites: list[str] | None = None,
               limit: int | None = None, delay: float = 6.0,
               dry_run: bool = False, fetch_sitemap=None, fetch_page=None,
               now: str | None = None) -> dict
    ```
    `sites=None` means every key of `SITES`, in `SITES` order.
    `fetch_sitemap`/`fetch_page` default to `None` and are resolved **inside
    the function body** to `backfill.fetch_all_post_sitemaps` /
    `backfill.fetch_page`. This deviates deliberately from `run_backfill`'s
    def-time defaults: a def-time default binds the real network function
    permanently, so a test that exercises `main()` could not substitute a
    fake and would hit the live sites. **`fetch_sitemap`
    is called as `fetch_sitemap(host=host)`** — a different call shape from
    `run_backfill`'s zero-argument `fetch_sitemap()`, which must not change.
    Returns
    `{"sites": {host: counts}, "totals": counts}` where `counts` has the keys
    `candidates`, `winner`, `non_winner`, `uncertain`, `skipped`,
    `dropped_out_of_window` (all `int`).
  - `main(argv: list[str] | None = None) -> int` — argparse flags
    `--data-dir` (default `best_of_sno`), `--since` (`2026-01-01`),
    `--until` (`2026-10-10`), `--sites` (comma-separated hosts; default all
    five; an unknown host calls `parser.error`), `--limit` (int, per site),
    `--delay` (float, `6.0`), `--dry-run`. Logs at INFO to
    `<data-dir>/logs/layer2.log` **and** the console.

  **Per-host loop:**
  1. Validate `since` and `until` with `backfill._require_iso_date`.
  2. `corpus = load_winner_corpus(data_dir)` — once, before any host.
  3. `done = load_layer2_state(...) | scraper._read_ids(layer2.csv) | scraper._read_ids(uncertain.csv)`
     — the union is what makes a re-run write no duplicate even if the
     checkpoint was lost.
  4. For each host: `parse_sitemap` over every `fetch_sitemap(host=host)`
     blob → `select_candidates(pairs, since)` → record `candidates` → drop
     locs whose `post_id_from_url(loc, host=host)` is in `done` → apply
     `limit`.
  5. `dry_run` reports candidate counts per host and returns **without
     fetching a single post page and without creating any file** (sitemaps
     are still fetched, exactly as `run_backfill` does).
  6. Per post: `fetch_page(loc)`; on any exception log a warning, `skipped
     += 1`, do **not** add to `done`, sleep, continue.
  7. `record = backfill.parse_post(html, loc, now, since=since, host=host)`.
     `None` → `dropped_out_of_window += 1`, mark done.
  8. Else set `record["source_site"] = host` (overriding the image-host
     guess — on a school's own site the host *is* the source, and spec §7
     requires this column populated).
  9. If `record["published"]` is non-empty and `> until` →
     `dropped_out_of_window += 1`, mark done, continue.
  10. `verdict = classify(record, corpus.get(SITES[host], []))`.
      `winner`/`non_winner` → `append_rows(layer2.csv, [record | {label, matched_id}], LAYER2_COLUMNS)`.
      `uncertain` → `append_rows(uncertain.csv, [record | {label, matched_id, reason, candidate_title, candidate_url}], UNCERTAIN_COLUMNS)`.
      Increment the matching counter; add the id to `done`.
  11. Save the checkpoint every `CHECKPOINT_EVERY` rows and after every host.
      `time.sleep(delay)` between post fetches within a host. Hosts are
      crawled sequentially, which is what makes one `delay` honor
      `Crawl-delay: 6` per host.
  12. Log per-host progress as
      `"%s: fetched %d/%d (winner=%d non=%d uncertain=%d)"`.

- [ ] **Step 1: Write the failing integration tests** in `best_of_sno/tests/test_layer2_run.py`

```python
import csv
from pathlib import Path
import pytest
from best_of_sno.layer2 import run_layer2, main
from best_of_sno.scraper import COLUMNS

FX = Path(__file__).parent / "fixtures" / "layer2"

def _page(title, author="Ada Lee", school="Carlmont High School", date="March 3, 2026"):
    byline = f"By {author}, {school} • {date}" if date else f"By {author}, {school}"
    return (f"<html><head><meta property='og:title' content='{title}'></head><body>"
            f"<span class='sno-story-byline'>{byline}</span>"
            f"<div class='sno-story-body-content'><p>{'word ' * 80}</p></div>"
            f"</body></html>").encode()

def _sitemap(host, ids):
    urls = "".join(
        f"<url><loc>https://{host}/{i}/news/story-{i}/</loc>"
        f"<lastmod>2026-03-03T10:00:00+00:00</lastmod></url>" for i in ids)
    return (f"<?xml version='1.0'?><urlset "
            f"xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{urls}</urlset>").encode()

def _archive(tmp_path, rows):
    d = tmp_path / "data"; d.mkdir(parents=True, exist_ok=True)
    with open(d / "archive.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval=""); w.writeheader()
        for r in rows:
            base = {c: "" for c in COLUMNS}; base.update(r); w.writerow(base)

def _rows(p):
    p = Path(p)
    return list(csv.DictReader(open(p, newline="", encoding="utf-8"))) if p.exists() else []

# One host, two posts: #1 is a known winner, #2 is not.
PAGES = {
    "https://scotscoop.com/1/news/story-1/": _page("Amputees redefine ability"),
    "https://scotscoop.com/2/news/story-2/": _page("A totally different story", author="Bo Chen"),
}
def fake_sitemap(*, host): return [_sitemap(host, [1, 2])]
def fake_page(url):
    if url not in PAGES: raise RuntimeError("boom")
    return PAGES[url]

def _seed(tmp_path):
    _archive(tmp_path, [{"id": "https://bestofsno.com/?p=83917",
                         "url": "https://bestofsno.com/83917/features/amputees/",
                         "title": "Amputees redefine ability", "published": "2026-03-03",
                         "author": "Ada Lee", "school": "Carlmont High School"}])

def test_labels_winner_and_non_winner_into_layer2(tmp_path):
    _seed(tmp_path)
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                     fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    rows = {r["id"]: r for r in _rows(tmp_path / "data" / "layer2.csv")}
    assert res["totals"]["winner"] == 1 and res["totals"]["non_winner"] == 1
    assert rows["https://scotscoop.com/?p=1"]["label"] == "winner"
    assert rows["https://scotscoop.com/?p=1"]["matched_id"] == "https://bestofsno.com/?p=83917"
    assert rows["https://scotscoop.com/?p=2"]["label"] == "non_winner"
    # every row carries the SCHOOL-SITE body and the host as source_site
    assert all(r["source_site"] == "scotscoop.com" for r in rows.values())
    assert all(int(r["word_count"]) > 50 for r in rows.values())

def test_undated_article_goes_to_uncertain_not_layer2(tmp_path):
    _seed(tmp_path)
    pages = {"https://scotscoop.com/1/news/story-1/":
             _page("Amputees redefine ability", date="")}
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                     fetch_sitemap=lambda *, host: [_sitemap(host, [1])],
                     fetch_page=lambda u: pages[u])
    assert res["totals"]["uncertain"] == 1 and res["totals"]["non_winner"] == 0
    assert _rows(tmp_path / "data" / "layer2.csv") == []
    u = _rows(tmp_path / "data" / "uncertain.csv")[0]
    assert u["reason"] == "undated" and u["label"] == "uncertain"

def test_article_published_after_until_is_dropped(tmp_path):
    _seed(tmp_path)
    pages = {"https://scotscoop.com/9/news/story-9/":
             _page("Late story", date="October 20, 2026")}
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], until="2026-10-10", delay=0,
                     fetch_sitemap=lambda *, host: [_sitemap(host, [9])],
                     fetch_page=lambda u: pages[u])
    assert res["totals"]["dropped_out_of_window"] == 1
    assert _rows(tmp_path / "data" / "layer2.csv") == []

def test_ids_never_collide_across_hosts(tmp_path):
    _seed(tmp_path)
    pages = {"https://scotscoop.com/1/news/story-1/": _page("Scotscoop story"),
             "https://elestoque.org/1/news/story-1/":
                 _page("Estoque story", school="Monta Vista High School")}
    res = run_layer2(str(tmp_path), sites=["scotscoop.com", "elestoque.org"], delay=0,
                     fetch_sitemap=lambda *, host: [_sitemap(host, [1])],
                     fetch_page=lambda u: pages[u])
    ids = {r["id"] for r in _rows(tmp_path / "data" / "layer2.csv")}
    assert ids == {"https://scotscoop.com/?p=1", "https://elestoque.org/?p=1"}
    assert res["totals"]["non_winner"] == 2

def test_dry_run_writes_nothing(tmp_path):
    _seed(tmp_path)
    fetched = []
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0, dry_run=True,
                     fetch_sitemap=fake_sitemap,
                     fetch_page=lambda u: fetched.append(u) or fake_page(u))
    assert res["sites"]["scotscoop.com"]["candidates"] == 2
    assert fetched == []
    assert not (tmp_path / "data" / "layer2.csv").exists()

def test_resume_refetches_nothing_and_writes_no_duplicate(tmp_path):
    _seed(tmp_path)
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    calls = []
    res2 = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                      fetch_sitemap=fake_sitemap,
                      fetch_page=lambda u: calls.append(u) or fake_page(u))
    assert calls == []
    assert res2["totals"]["winner"] == 0 and res2["totals"]["non_winner"] == 0
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2

def test_resume_works_from_the_csvs_alone(tmp_path):
    _seed(tmp_path)
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    (tmp_path / "data" / "layer2_state.json").unlink()  # lost checkpoint
    calls = []
    run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
               fetch_sitemap=fake_sitemap,
               fetch_page=lambda u: calls.append(u) or fake_page(u))
    assert calls == []
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2

def test_fetch_failure_is_skipped_and_retried_next_run(tmp_path):
    _seed(tmp_path)
    bad = "https://scotscoop.com/2/news/story-2/"
    def flaky(url):
        if url == bad: raise RuntimeError("boom")
        return PAGES[url]
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                     fetch_sitemap=fake_sitemap, fetch_page=flaky)
    assert res["totals"]["skipped"] == 1 and res["totals"]["winner"] == 1
    res2 = run_layer2(str(tmp_path), sites=["scotscoop.com"], delay=0,
                      fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert res2["totals"]["non_winner"] == 1  # the skipped id was retried
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 2

def test_limit_caps_posts_per_site(tmp_path):
    _seed(tmp_path)
    res = run_layer2(str(tmp_path), sites=["scotscoop.com"], limit=1, delay=0,
                     fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert len(_rows(tmp_path / "data" / "layer2.csv")) == 1
    assert res["sites"]["scotscoop.com"]["candidates"] == 2

def test_non_iso_until_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_layer2(str(tmp_path), until="2026-1-1", delay=0,
                   fetch_sitemap=fake_sitemap, fetch_page=fake_page)

def test_main_dry_run_returns_zero(tmp_path, monkeypatch):
    # Patches the module attribute, which only works because run_layer2
    # resolves its fetchers at call time rather than at def time.
    _seed(tmp_path)
    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps",
                        lambda **kw: [_sitemap(kw["host"], [1])])
    assert main(["--data-dir", str(tmp_path), "--sites", "scotscoop.com",
                 "--dry-run", "--delay", "0"]) == 0

def test_main_never_touches_the_network_without_a_fake(tmp_path, monkeypatch):
    # Guards the late-binding contract itself: if run_layer2 ever reverts to
    # def-time defaults, this test starts making real HTTP requests instead
    # of raising, and fails loudly.
    def boom(**kw):
        raise AssertionError("real sitemap fetcher was called")
    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps", boom)
    with pytest.raises(AssertionError, match="real sitemap fetcher"):
        main(["--data-dir", str(tmp_path), "--sites", "scotscoop.com", "--dry-run"])

def test_main_rejects_an_unknown_site(tmp_path):
    with pytest.raises(SystemExit):
        main(["--data-dir", str(tmp_path), "--sites", "example.com", "--dry-run"])
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest best_of_sno/tests/test_layer2_run.py -v`
Expected: FAIL — `run_layer2` / `main` not defined.

- [ ] **Step 3: Implement `CHECKPOINT_EVERY`, `run_layer2`, and `main`** in
`best_of_sno/layer2.py`, following the per-host loop above. Mirror
`backfill.main`'s logging setup, pointing at `logs/layer2.log`.

- [ ] **Step 4: Run the whole suite, verify it is green**

Run: `.venv/bin/python -m pytest best_of_sno/tests -v`
Expected: PASS — the 53 pre-existing tests (unchanged) plus every test added
in Tasks 1–6.

- [ ] **Step 5: Commit**

```bash
git add best_of_sno/layer2.py best_of_sno/tests/test_layer2_run.py
git commit -m "feat: layer2 per-host crawl orchestration + CLI"
```

---

## Post-implementation (manual, not tasks)

1. **Confirm the backfill is untouched in substance:**
   `git diff main -- best_of_sno/backfill.py` should show only added
   parameters, the `_require_iso_date` extraction, and docstrings.
2. **Trial run, one site, tiny:**
   `python -m best_of_sno.layer2 --sites scotscoop.com --limit 5` → inspect
   `layer2.csv` for 5 well-formed rows with sane labels before going wide.
3. **Dry run, all five:** `python -m best_of_sno.layer2 --dry-run` → expect
   roughly 4,000 candidates total (~818 on Scotscoop).
4. **Full run overnight:** `python -m best_of_sno.layer2` (~6.7 hours,
   resumable — safe to interrupt and restart).
5. **Review `uncertain.csv` by hand.** It is deliberately held out of
   training until each row is ruled on.
6. **Sanity-check the label distribution:** expect on the order of ~94
   winners against ~3,900 non-winners. A winner count far below that means
   the title-match rule is too strict — check `uncertain.csv` first.
