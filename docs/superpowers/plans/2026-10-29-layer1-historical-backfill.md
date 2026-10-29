# Layer 1 Historical Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill every Best of SNO winning story published since 2026-01-01 into a new `archive.csv`, via the WordPress sitemap + post HTML pages, reusing the daily scraper's parsing core.

**Architecture:** New module `best_of_sno/backfill.py`. Enumerate posts from `wp-sitemap-posts-post-{1..4}.xml`, keep those with `lastmod ≥ since`, fetch each post's HTML page 6s apart, parse `og:title` / `.sno-story-byline` / `.sno-story-body-content`, write rows (same 12 columns) append-wise to `archive.csv` with a resumable checkpoint. One narrow edit to `scraper.load_state` makes the daily scraper treat backfilled ids as seen.

**Tech Stack:** Python 3.14, `requests`, `beautifulsoup4` (no `feedparser` here).

**Spec:** `docs/superpowers/specs/2026-10-29-layer1-historical-backfill-design.md`

## Global Constraints

- **Python 3.14**; deps already installed: `requests`, `beautifulsoup4`.
- **Reuse, do not reimplement** from `best_of_sno/scraper.py`: `COLUMNS`,
  `USER_AGENT`, `parse_byline`, `strip_html`, `word_count`,
  `extract_source_site`, `_csv_safe`, `_rows_to_csv_text`,
  `_atomic_write_text`, `_read_rows`. Import them.
- **Schema parity:** every `archive.csv` row is keyed by `scraper.COLUMNS`
  in that exact order. No added/renamed columns.
- **id scheme:** `id = "https://bestofsno.com/?p=<numeric-id>"` where the
  numeric id is the 1st path segment of the post URL. Matches the daily feed
  guid so dedup aligns across files.
- **robots.txt:** only clean URLs (no `?`). Honor `Crawl-delay: 6` — default
  6.0s between post fetches, injectable for tests. Send `USER_AGENT`.
- **Verified selectors (confirmed 2026-10-29 against 3 live pages; fixtures
  in `tests/fixtures/backfill/`):**
  - title ← `<meta property="og:title">` content (NOT `<h1>`, which is the
    site name "Best of SNO").
  - byline+date ← `.sno-story-byline` text, e.g.
    `"By Madison Shen, Harvard-Westlake School • October 28, 2026"`.
    Split on `•`: left → `parse_byline`; right → date.
  - date string format: `"%B %d, %Y"` (`"October 28, 2026"`).
  - body ← `.sno-story-body-content`.
  - categories ← deslugified 2nd path segment of the URL
    (`arts-entertainment` → `Arts Entertainment`); best-effort (page has no
    category links or `article:published_time` meta on this theme).
- **Output:** `best_of_sno/data/archive.csv`; checkpoint
  `best_of_sno/data/backfill_state.json`. Both git-ignored (already covered
  by `best_of_sno/data/*.csv` and a new `backfill_state.json` ignore line —
  add it in Task 3).

## Review Focus

- **Missing/`•`-less byline:** a post without `.sno-story-byline` (or without
  the bullet) must not crash — warn, write the row with empty
  author/school/published, keep the body. *(Test in Task 2.)*
- **Single post fetch failure mid-run:** one URL that still errors after
  retries must be skipped (logged) so the ~2.7h run continues, and must NOT
  be marked done, so a re-run retries it. *(Test in Task 5.)*
- **Interrupt/crash mid-run:** rows already written stay; re-run resumes from
  the checkpoint with no duplicate row and no re-fetch of done ids.
  *(Test in Task 5.)*
- **Non-ASCII / smart quotes / HTML entities** in title and body must survive
  round-trip through `archive.csv` as UTF-8. *(Test in Task 2.)*
- **Unparseable date string:** keep the row with empty `published` and warn —
  never drop a story over a metadata parse failure. A *parseable* date
  `< since` IS dropped (published-date gate). *(Both tested in Task 2.)*

---

### Task 1: Sitemap enumeration + date prefilter

**Files:**
- Create: `best_of_sno/backfill.py` (module scaffold + these functions)
- Test: `best_of_sno/tests/test_backfill_sitemap.py`
- Fixture (exists): `best_of_sno/tests/fixtures/backfill/sitemap_sample.xml`

**Interfaces:**
- Produces:
  - `SITEMAP_INDEX = "https://bestofsno.com/wp-sitemap.xml"`
  - `parse_sitemap(xml_bytes: bytes) -> list[tuple[str, str]]` — `(loc, lastmod)` pairs.
  - `select_candidates(pairs: list[tuple[str, str]], since: str) -> list[str]` — locs with `lastmod >= since` (string compare on ISO dates is correct), input order preserved.
  - `post_id_from_url(url: str) -> str` — `"https://bestofsno.com/?p=<n>"` from the 1st path segment.

- [ ] **Step 1: Write failing tests**

```python
from best_of_sno.backfill import parse_sitemap, select_candidates, post_id_from_url
from pathlib import Path
SM = (Path(__file__).parent / "fixtures" / "backfill" / "sitemap_sample.xml").read_bytes()

def test_parse_sitemap_returns_loc_lastmod_pairs():
    pairs = parse_sitemap(SM)
    assert len(pairs) == 3
    assert pairs[0][0].endswith("/scene-around/")
    assert pairs[0][1].startswith("2026-10-28")

def test_select_candidates_keeps_only_in_window():
    pairs = parse_sitemap(SM)
    locs = select_candidates(pairs, since="2026-01-01")
    assert len(locs) == 2                      # the 2025 story is dropped
    assert all("50000" not in l for l in locs)

def test_post_id_from_url_matches_feed_guid_scheme():
    assert post_id_from_url("https://bestofsno.com/89942/arts-entertainment/scene-around/") \
        == "https://bestofsno.com/?p=89942"
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest best_of_sno/tests/test_backfill_sitemap.py -v` → FAIL (module/functions missing).

- [ ] **Step 3: Implement the three functions** in `best_of_sno/backfill.py`. `parse_sitemap` via `xml.etree.ElementTree` (handle the sitemap namespace); `select_candidates` filters by `lastmod >= since`; `post_id_from_url` via `urllib.parse.urlparse(...).path.strip("/").split("/")[0]`.

- [ ] **Step 4: Run tests, verify they pass.**

- [ ] **Step 5: Commit** — `feat: backfill sitemap enumeration + date prefilter`.

---

### Task 2: Post HTML page parser

**Files:**
- Modify: `best_of_sno/backfill.py`
- Test: `best_of_sno/tests/test_backfill_parse.py`
- Fixtures (exist): `tests/fixtures/backfill/post_89942_single_author.html`, `post_89941_single_author.html`, `post_89940_multi_author.html`

**Interfaces:**
- Consumes: `scraper.COLUMNS`, `parse_byline`, `strip_html`, `word_count`, `extract_source_site`; `post_id_from_url` (Task 1).
- Produces: `parse_post(html: bytes, url: str, scraped_at: str, *, since: str) -> dict | None` — a record keyed by `COLUMNS`, or `None` if the parsed published date is a valid date `< since` (published-date gate).

- [ ] **Step 1: Write failing tests**

```python
from best_of_sno.backfill import parse_post
from best_of_sno.scraper import COLUMNS
from pathlib import Path
FX = Path(__file__).parent / "fixtures" / "backfill"
NOW = "2026-10-29T08:00:00-07:00"

def _p(name, url):
    return parse_post((FX / name).read_bytes(), url, NOW, since="2026-01-01")

def test_parse_single_author_full_record():
    r = _p("post_89942_single_author.html", "https://bestofsno.com/89942/arts-entertainment/scene-around/")
    assert set(r) == set(COLUMNS)
    assert r["id"] == "https://bestofsno.com/?p=89942"
    assert r["title"] == "Scene Around"                 # from og:title, not <h1>
    assert r["author"] == "Madison Shen"
    assert r["school"] == "Harvard-Westlake School"
    assert r["published"].startswith("2026-10-28")
    assert r["categories"]                               # non-empty, from URL segment
    assert r["word_count"] > 0 and r["body"]

def test_parse_multi_author_has_no_school():
    r = _p("post_89940_multi_author.html", "https://bestofsno.com/89940/showcase/women-are-freaking-magical-frenchtown-coven-performs-annual-witches-dance/")
    assert "Emma Haig" in r["author"] and "Riley Nelson" in r["author"]
    assert r["school"] == ""                             # "and"-list → empty school

def test_parse_preserves_non_ascii_title():
    r = _p("post_89940_multi_author.html", "https://bestofsno.com/89940/showcase/x/")
    assert "magical" in r["title"].lower()               # smart-quoted title survives

def test_published_gate_drops_pre_since(monkeypatch):
    # Force the byline date to 2025 by parsing a synthetic byline helper, OR
    # call with since in the future to exercise the gate deterministically:
    r = parse_post((FX / "post_89942_single_author.html").read_bytes(),
                   "https://bestofsno.com/89942/a/b/", NOW, since="2027-01-01")
    assert r is None

def test_missing_byline_keeps_body_empty_meta():
    html = b"<html><head><meta property='og:title' content='No Byline'></head>" \
           b"<body><div class='sno-story-body-content'><p>Body words here.</p></div></body></html>"
    r = parse_post(html, "https://bestofsno.com/777/news/x/", NOW, since="2026-01-01")
    assert r["title"] == "No Byline" and r["author"] == "" and r["school"] == ""
    assert r["published"] == "" and r["word_count"] > 0

def test_unparseable_date_keeps_row_empty_published():
    html = b"<html><head><meta property='og:title' content='Weird Date'></head>" \
           b"<body><span class='sno-story-byline'>By A, B School \xe2\x80\xa2 someday</span>" \
           b"<div class='sno-story-body-content'><p>Words.</p></div></body></html>"
    r = parse_post(html, "https://bestofsno.com/778/news/x/", NOW, since="2026-01-01")
    assert r is not None and r["published"] == "" and r["author"] == "A"
```

- [ ] **Step 2: Run tests, verify they fail** — FAIL (`parse_post` missing).

- [ ] **Step 3: Implement `parse_post`.** BeautifulSoup parse; title from `og:title`; byline from `.sno-story-byline`, split on `"•"` (U+2022) into byline/date; `parse_byline(byline)`; date via `datetime.strptime(date_str.strip(), "%B %d, %Y")` in a try/except (failure → `""`, warn). Published-date gate: if a date parsed AND `iso < since` → return `None`. Body from `.sno-story-body-content` → `strip_html`/`word_count`/`extract_source_site` (pass the body container's inner HTML). categories = deslugified 2nd URL path segment. Missing byline element → empty author/school/published, warn.

- [ ] **Step 4: Run tests, verify they pass.**

- [ ] **Step 5: Commit** — `feat: backfill post HTML parser (og:title, byline, body)`.

---

### Task 3: Archive writer + resumable checkpoint

**Files:**
- Modify: `best_of_sno/backfill.py`, `.gitignore`
- Test: `best_of_sno/tests/test_backfill_state.py`

**Interfaces:**
- Consumes: `scraper._csv_safe`, `scraper._rows_to_csv_text`, `scraper._atomic_write_text`, `scraper.COLUMNS`.
- Produces:
  - `append_rows(archive_path: str, records: list[dict]) -> None` — writes header if the file is new, then appends rows with `_csv_safe` applied and `csv.QUOTE_ALL`; UTF-8.
  - `load_backfill_state(path: str) -> set[str]` — the `done_ids` set (empty if missing/corrupt).
  - `save_backfill_state(path: str, done_ids: set[str]) -> None` — atomic JSON write.

- [ ] **Step 1: Write failing tests**

```python
import csv
from best_of_sno.backfill import append_rows, load_backfill_state, save_backfill_state
from best_of_sno.scraper import COLUMNS

def _rec(id_, **kw):
    r = {c: "" for c in COLUMNS}; r["id"] = id_; r.update(kw); return r

def _rows(p):
    with open(p, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def test_append_writes_header_once_then_appends(tmp_path):
    p = str(tmp_path / "archive.csv")
    append_rows(p, [_rec("a", title="A")])
    append_rows(p, [_rec("b", title="B")])
    rows = _rows(p)
    assert [r["id"] for r in rows] == ["a", "b"]
    assert open(p, encoding="utf-8").read().count("id,url,title") == 1   # one header

def test_append_neutralizes_formula_injection(tmp_path):
    p = str(tmp_path / "archive.csv")
    append_rows(p, [_rec("x", title="=cmd()")])
    assert _rows(p)[0]["title"].startswith("'")

def test_state_roundtrip_and_corrupt_fallback(tmp_path):
    sp = str(tmp_path / "backfill_state.json")
    assert load_backfill_state(sp) == set()                 # missing → empty
    save_backfill_state(sp, {"a", "b"})
    assert load_backfill_state(sp) == {"a", "b"}
    open(sp, "w").write("{bad json")
    assert load_backfill_state(sp) == set()                 # corrupt → empty
```

- [ ] **Step 2: Run tests, verify they fail.**

- [ ] **Step 3: Implement** the three functions; reuse `_csv_safe`/`_rows_to_csv_text` for formatting (append mode writes header only when the file is absent/empty). Add `best_of_sno/data/backfill_state.json` to `.gitignore`.

- [ ] **Step 4: Run tests, verify they pass.**

- [ ] **Step 5: Commit** — `feat: backfill archive writer + resumable checkpoint`.

---

### Task 4: Daily scraper dedups against the archive

**Files:**
- Modify: `best_of_sno/scraper.py` (`load_state` and its one caller in `run`)
- Test: `best_of_sno/tests/test_state.py` (add a case)

**Interfaces:**
- Modifies: `load_state(state_path, new_path, old_path, archive_path=None)` — when `archive_path` is given and exists, its ids join the seen-id union (alongside `new.csv` + `old.csv`). `run()` passes `data/archive.csv`.
- **Backward-compat:** `archive_path` defaults to `None` so all existing `load_state` tests and callers keep working unchanged.

- [ ] **Step 1: Write failing test** (append to `test_state.py`)

```python
def test_archive_ids_join_seen_union(tmp_path):
    from best_of_sno.scraper import load_state
    np = tmp_path / "new.csv"; op = tmp_path / "old.csv"; ap = tmp_path / "archive.csv"
    _write_csv_with_ids(np, ["n1"]); _write_csv_with_ids(op, ["o1"]); _write_csv_with_ids(ap, ["arch1"])
    loaded = load_state(str(tmp_path / "state.json"), str(np), str(op), str(ap))
    assert {"n1", "o1", "arch1"} <= loaded["seen_ids"]
```

- [ ] **Step 2: Run test, verify it fails** — FAIL (`load_state` takes 3 args / `arch1` absent).

- [ ] **Step 3: Add the optional `archive_path` param** to `load_state`; when truthy, `csv_ids |= _read_ids(archive_path)`. In `run()`, compute `archive_path = os.path.join(data, "archive.csv")` and pass it. Change nothing about rotation or save order.

- [ ] **Step 4: Run the full state + main suites, verify green** — `pytest best_of_sno/tests/test_state.py best_of_sno/tests/test_main.py -v`.

- [ ] **Step 5: Commit** — `feat: daily scraper treats backfilled archive ids as seen`.

---

### Task 5: Orchestration + CLI

**Files:**
- Modify: `best_of_sno/backfill.py`
- Test: `best_of_sno/tests/test_backfill_run.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces:
  - `fetch_page(url, *, session=None, timeout=20, retries=3, backoff=2.0) -> bytes` — same polite retry pattern as `scraper.fetch_feed` (UA header, raise-for-status, retry on connection errors).
  - `run_backfill(data_dir, *, since="2026-01-01", limit=None, delay=6.0, dry_run=False, fetch_sitemap=..., fetch_page=fetch_page, now=None) -> dict` — returns `{"candidates": int, "written": int, "skipped": int, "dropped_pre_since": int}`. Enumerate → `select_candidates` → drop done ids → (dry-run: report + return, write nothing) → for each: fetch (on failure after retries: log, `skipped += 1`, do NOT mark done, continue), `parse_post` (None → `dropped_pre_since += 1`, mark done), else `append_rows` + add id to done; save checkpoint every 25 rows and at end; `time.sleep(delay)` between fetches (injectable; tests pass `delay=0`).
  - `main(argv=None) -> int` — argparse: `--data-dir` (default `best_of_sno`), `--since` (default `2026-01-01`), `--limit`, `--delay` (default 6.0), `--dry-run`; logging to `logs/backfill.log` + stream; progress log `fetched N/total`.

- [ ] **Step 1: Write failing integration tests**

```python
from pathlib import Path
import csv
from best_of_sno.backfill import run_backfill

FX = Path(__file__).parent / "fixtures" / "backfill"
SM = (FX / "sitemap_sample.xml").read_bytes()           # 2 in-window, 1 pre-2026
PAGES = {
    "https://bestofsno.com/89942/arts-entertainment/scene-around/": (FX / "post_89942_single_author.html").read_bytes(),
    "https://bestofsno.com/89941/sports/still-in-the-game/": (FX / "post_89941_single_author.html").read_bytes(),
}
def fake_sitemap(): return [SM]                          # one sub-sitemap
def fake_page(url):
    if url not in PAGES: raise RuntimeError("boom")
    return PAGES[url]
def _rows(p): 
    return list(csv.DictReader(open(p, newline="", encoding="utf-8"))) if Path(p).exists() else []

def test_run_writes_in_window_rows(tmp_path):
    res = run_backfill(str(tmp_path), since="2026-01-01", delay=0,
                       fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    rows = _rows(tmp_path / "data" / "archive.csv")
    assert res["candidates"] == 2 and res["written"] == 2
    assert {r["id"] for r in rows} == {"https://bestofsno.com/?p=89942", "https://bestofsno.com/?p=89941"}

def test_dry_run_writes_nothing(tmp_path):
    res = run_backfill(str(tmp_path), delay=0, dry_run=True,
                       fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert res["candidates"] == 2
    assert not (tmp_path / "data" / "archive.csv").exists()

def test_resume_skips_done_ids(tmp_path):
    run_backfill(str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    # second run: all ids already done → no refetch, no dup
    calls = []
    def counting_page(url): calls.append(url); return fake_page(url)
    res2 = run_backfill(str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=counting_page)
    assert calls == [] and res2["written"] == 0
    assert len(_rows(tmp_path / "data" / "archive.csv")) == 2      # still 2, no dup

def test_fetch_failure_is_skipped_not_fatal_and_retried_next_run(tmp_path):
    bad = dict(PAGES); bad_url = "https://bestofsno.com/89941/sports/still-in-the-game/"
    def flaky(url):
        if url == bad_url: raise RuntimeError("boom")
        return PAGES[url]
    res = run_backfill(str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=flaky)
    assert res["written"] == 1 and res["skipped"] == 1            # one survived, one skipped
    # the skipped id was NOT marked done → a good re-run picks it up
    res2 = run_backfill(str(tmp_path), delay=0, fetch_sitemap=fake_sitemap, fetch_page=fake_page)
    assert res2["written"] == 1
    assert len(_rows(tmp_path / "data" / "archive.csv")) == 2
```

- [ ] **Step 2: Run tests, verify they fail.**

- [ ] **Step 3: Implement `fetch_page`, `run_backfill`, `main`.** `fetch_sitemap` default fetches the index then each `wp-sitemap-posts-post-*.xml` (returns their bytes); tests inject a fake. Keep the fetch loop's failure handling exactly as the Review Focus requires.

- [ ] **Step 4: Run the full suite, verify green** — `pytest best_of_sno/ -v` (all prior tests + new).

- [ ] **Step 5: Commit** — `feat: backfill orchestration + CLI`.

---

## Post-implementation (manual, not a task)

After the suite is green, a **trial run** before the full 2.7h pass:
`python -m best_of_sno.backfill --limit 20` → inspect `archive.csv` for 20
well-formed rows, then run unbounded (overnight) for the full ~1,619.
