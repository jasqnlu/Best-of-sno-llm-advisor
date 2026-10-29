# Layer 1 Daily Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A once-a-day Python job that pulls newly published Best of SNO stories from the RSS feed and keeps a de-duplicated, crash-safe CSV archive split into `new` (today) and `old` (everything earlier).

**Architecture:** One focused module, `best_of_sno/scraper.py`, built from pure parsing helpers, thin I/O functions, and a `main()` that wires the 8-step daily flow. Network fetch is isolated in one function so everything else tests offline against a fixture feed. Stdlib `csv` + `json` for storage (no pandas); `requests` for fetching; `feedparser` for RSS; `beautifulsoup4` for HTML stripping and image-host extraction. All file writes go `*.tmp` → `os.replace`; `state.json` is written last.

**Tech Stack:** Python 3.14, `requests`, `feedparser`, `beautifulsoup4`, stdlib `csv`/`json`/`argparse`/`logging`.

**Spec:** `docs/superpowers/specs/2026-10-28-best-of-sno-advisor-design.md` (Layer 1 is §5; the rest of the doc is later phases, not built here).

## Global Constraints

- **Python 3.14**; keep dependencies to `requests`, `feedparser`, `beautifulsoup4` only (stdlib for CSV/JSON).
- **robots.txt (verified 2026-10-28):** only the no-query-string `/feed/` path is fetched by the daily job. **Never** build a URL with a query string (`?`). Honor **`Crawl-delay: 6`** for any multi-request fetching (not triggered by the daily single-feed fetch).
- **User-Agent:** `BestOfSNO-research-scraper (07jasonlu2010@gmail.com)` on every request, with a timeout and retries.
- **CSV column order (both files), exact:** `id, url, title, published, categories, author, school, summary, body, word_count, source_site, scraped_at`.
- **Rotation policy:** rotate **every run** (even zero new stories), unless `--no-rotate`.
- **Copyright/etiquette:** store full text locally only; never republish; link to originals.

## Review Focus

- **Excerpt-only item (no `<content:encoded>`):** `body` empty, `word_count` 0, `source_site` empty — no crash. → Task 2 test.
- **Multi-author byline with no school (`By A, B, and C`):** `author` captured, `school` empty — no crash, never mistakes a name for a school. → Task 1 test.
- **Missing/corrupt `state.json`:** `seen_ids` rebuilt from `old.csv` + `new.csv`, and already-stored stories are not re-added. → Task 4 test.
- **Body containing commas, quotes, and newlines:** survives a CSV write→read round-trip unchanged (proper quoting). → Task 5 test.
- **Same `guid` seen on a later run:** not added again (dedup via `seen_ids`, not CSV absence). → Task 6 test.

---

### Task 1: Scaffolding + pure parsing helpers

**Files:**
- Create: `best_of_sno/scraper.py`
- Create: `best_of_sno/requirements.txt`
- Create: `best_of_sno/__init__.py` (empty)
- Test: `best_of_sno/tests/test_parsing.py`
- Create: `best_of_sno/tests/__init__.py` (empty)

**Interfaces:**
- Produces:
  - `COLUMNS: list[str]` — the exact column order from Global Constraints.
  - `strip_html(html: str) -> str` — visible text, whitespace-collapsed, `''` for empty/None.
  - `word_count(text: str) -> int` — number of whitespace-separated tokens.
  - `parse_byline(creator: str) -> tuple[str, str]` — returns `(author, school)`.
  - `extract_source_site(body_html: str) -> str` — originating school domain, or `''`.

- [ ] **Step 1: Write failing tests** in `best_of_sno/tests/test_parsing.py`:

```python
def test_strip_html_removes_tags_and_collapses_ws():
    assert strip_html("<p>Hello  <b>world</b></p>\n") == "Hello world"
def test_strip_html_empty():
    assert strip_html("") == "" and strip_html(None) == ""
def test_word_count():
    assert word_count("one two three") == 3 and word_count("") == 0
def test_parse_byline_author_and_school():
    assert parse_byline("By Talia Rosenthal, Torrey Pines High School") == ("Talia Rosenthal", "Torrey Pines High School")
def test_parse_byline_multi_author_no_school():
    assert parse_byline("By Ben Balian, Jack Martin, and Will Simpson") == ("Ben Balian, Jack Martin, and Will Simpson", "")
def test_parse_byline_plain():
    assert parse_byline("By Jane Doe") == ("Jane Doe", "")
def test_extract_source_site_from_image_host():
    html = '<p>x</p><img src="https://torreypinesfalconer.com/wp-content/uploads/2026/10/a.png"/>'
    assert extract_source_site(html) == "torreypinesfalconer.com"
def test_extract_source_site_ignores_platform_hosts():
    html = '<img src="https://bestofsno.com/x.png"/><img src="https://secure.gravatar.com/y.png"/>'
    assert extract_source_site(html) == ""
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest best_of_sno/tests/test_parsing.py -v` → FAIL (names not defined).

- [ ] **Step 3: Implement the helpers in `best_of_sno/scraper.py`.**
  - `strip_html`: BeautifulSoup `get_text(" ")` then collapse runs of whitespace to single spaces and strip.
  - `parse_byline`: strip a leading `By ` (case-insensitive); the heuristic — the school is the **final comma-separated segment only when** the byline has author name(s) before it **and** that last segment is not part of an `", and "`/`" and "` author list. Concretely: if the string contains `" and "` (a multi-author list), return `(whole_remainder, "")`; else if there is at least one comma, the last comma-segment is `school` and the rest is `author`; else `(remainder, "")`. Trim each piece.
  - `extract_source_site`: BeautifulSoup over the HTML, collect `img[src]` hosts (`urllib.parse.urlparse(src).netloc`, lowercased, strip leading `www.`); ignore hosts matching `bestofsno.com`, `*.wordpress.org`, `*.w.org`, `gravatar.com`, `secure.gravatar.com`, `gstatic.com`, `googleapis.com`; return the most common remaining host, or `''`.
  - `COLUMNS` constant set to the Global-Constraints order.
  - `requirements.txt`: `requests`, `feedparser`, `beautifulsoup4`.

- [ ] **Step 4: Run tests, verify they pass** — `pytest best_of_sno/tests/test_parsing.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add best_of_sno && git commit -m "feat: parsing helpers for Best of SNO scraper"`.

---

### Task 2: `parse_items` — feed bytes → records

**Files:**
- Modify: `best_of_sno/scraper.py`
- Test: `best_of_sno/tests/test_parse_items.py`
- Create: `best_of_sno/tests/fixtures/feed_sample.xml`

**Interfaces:**
- Consumes: Task 1 helpers + `COLUMNS`.
- Produces: `parse_items(feed_bytes: bytes, scraped_at: str) -> list[dict]` — one dict per `<item>` keyed by exactly `COLUMNS`. `id`←`guid`, `url`←`link`, `title`, `published`←`pubDate` as ISO-8601 (tz-aware; use `email.utils.parsedate_to_datetime(...).isoformat()`, falling back to the raw string if unparseable), `categories`←all `<category>` joined with `;`, `(author, school)`←`parse_byline(dc:creator)`, `summary`←`strip_html(description)`, `body`←`strip_html(content:encoded)` (`''` if absent), `word_count`←`word_count(body)`, `source_site`←`extract_source_site(content:encoded raw)`, `scraped_at` passed through.

- [ ] **Step 1: Create the fixture** `feed_sample.xml` — a minimal valid RSS 2.0 feed with the `content:` and `dc:` namespaces and **three** `<item>`s: (a) a normal story with `content:encoded` containing an `<img>` on a school domain and a `By Name, School` byline; (b) a multi-author story (`By A, B, and C`) with a body but no school image; (c) an excerpt-only story with a `<description>` but **no** `<content:encoded>`.

- [ ] **Step 2: Write failing tests** in `test_parse_items.py` (load the fixture bytes):

```python
def test_parses_all_items():
    assert len(records) == 3
def test_normal_item_fields():
    r = records[0]
    assert set(r.keys()) == set(COLUMNS)
    assert r["author"] == "<expected>" and r["school"] == "<expected>"
    assert r["source_site"] == "<school-domain>" and r["word_count"] > 0
    assert r["published"].startswith("2026-")
def test_excerpt_only_item_has_empty_body():
    r = records[2]
    assert r["body"] == "" and r["word_count"] == 0 and r["source_site"] == ""
def test_multi_author_item_has_no_school():
    r = records[1]
    assert r["school"] == "" and "," in r["author"]
```

- [ ] **Step 3: Run, verify fail** — `pytest best_of_sno/tests/test_parse_items.py -v` → FAIL.
- [ ] **Step 4: Implement `parse_items`** using `feedparser.parse(feed_bytes)`; read `content:encoded` via `entry.content[0].value` when present (guard with `getattr`/truthiness). Keep raw `content:encoded` for `extract_source_site`, stripped for `body`.
- [ ] **Step 5: Run, verify pass** → PASS.
- [ ] **Step 6: Commit** — `git commit -am "feat: parse_items feed→records with fixture"`.

---

### Task 3: `fetch_feed` — polite network fetch

**Files:**
- Modify: `best_of_sno/scraper.py`
- Test: `best_of_sno/tests/test_fetch.py`

**Interfaces:**
- Produces: `fetch_feed(url: str, *, session=None, timeout: int = 20, retries: int = 3) -> bytes` — GETs with the Global-Constraints User-Agent, raises for HTTP errors, retries on network/5xx with a short backoff, returns `response.content`.

- [ ] **Step 1: Write failing tests** using a fake session object (no real network):

```python
def test_sends_user_agent_and_returns_bytes():
    # fake session records headers, returns 200 with b"<rss/>"
    assert out == b"<rss/>"
    assert "BestOfSNO-research-scraper" in sent_headers["User-Agent"]
def test_retries_then_succeeds():
    # fake session raises ConnectionError twice, then returns 200
    assert fake.call_count == 3 and out == b"ok"
```

- [ ] **Step 2: Run, verify fail** → FAIL.
- [ ] **Step 3: Implement `fetch_feed`** with `requests`; accept an injected `session` for tests (default `requests.Session()`); loop up to `retries`, sleeping a small backoff between attempts; `raise_for_status()`.
- [ ] **Step 4: Run, verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: polite fetch_feed with UA, timeout, retries"`.

---

### Task 4: State — load, save, rebuild

**Files:**
- Modify: `best_of_sno/scraper.py`
- Test: `best_of_sno/tests/test_state.py`

**Interfaces:**
- Consumes: `COLUMNS`.
- Produces:
  - `load_state(state_path: str, new_path: str, old_path: str) -> dict` — returns `{"last_run": str|None, "seen_ids": set[str]}`; if `state_path` missing or unparseable, rebuild `seen_ids` from the `id` column of `old_path` + `new_path` (missing CSVs → empty).
  - `save_state(state_path: str, state: dict) -> None` — JSON with `seen_ids` as a sorted list; atomic (`*.tmp` → `os.replace`).

- [ ] **Step 1: Write failing tests** (use `tmp_path`):

```python
def test_save_then_load_roundtrip():
    # seen_ids survive as a set
def test_missing_state_rebuilds_from_csvs():
    # write old.csv+new.csv with known ids, no state.json
    assert loaded["seen_ids"] == {"id-a", "id-b", "id-c"}
def test_corrupt_state_falls_back_to_csvs():
    # state.json = "{bad json" → rebuilt from CSVs, no raise
def test_save_is_atomic_no_tmp_left():
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())
```

- [ ] **Step 2: Run, verify fail** → FAIL.
- [ ] **Step 3: Implement `load_state`/`save_state`** per signatures; a small `_read_ids(path)` helper reads the `id` column with `csv.DictReader` (missing file → `set()`).
- [ ] **Step 4: Run, verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: state load/save with CSV rebuild"`.

---

### Task 5: CSV I/O — `write_new` and `rotate`

**Files:**
- Modify: `best_of_sno/scraper.py`
- Test: `best_of_sno/tests/test_csv_io.py`

**Interfaces:**
- Consumes: `COLUMNS`.
- Produces:
  - `write_new(new_path: str, records: list[dict]) -> None` — atomically writes a CSV with the `COLUMNS` header + one row per record (`csv.DictWriter`, `restval=""`, `extrasaction="ignore"`). Empty list → header-only file.
  - `rotate(new_path: str, old_path: str) -> int` — append every data row of `new_path` onto `old_path` (writing `old_path`'s header first if it doesn't exist), then rewrite `new_path` as header-only. Returns rows moved. Missing/empty `new_path` → moves 0, still ensures a header-only `new_path`. Atomic for both files.

- [ ] **Step 1: Write failing tests** (`tmp_path`):

```python
def test_write_new_roundtrips_special_chars():
    rec = {**base, "body": 'He said, "hi"\nnew line, with comma'}
    # write then csv.DictReader back → body identical
def test_write_new_empty_is_header_only():
    # 0 data rows, header present
def test_rotate_moves_rows_and_clears_new():
    moved = rotate(new, old)
    assert moved == 2 and old_rowcount == 2 and new_rowcount == 0
def test_rotate_appends_to_existing_old():
    # old already has 1 row; after rotate of 2 → old has 3
```

- [ ] **Step 2: Run, verify fail** → FAIL.
- [ ] **Step 3: Implement `write_new`/`rotate`** with a shared atomic-write helper (`_atomic_write(path, rows)`), `csv` module, `newline=""`.
- [ ] **Step 4: Run, verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: atomic CSV write_new and rotate"`.

---

### Task 6: `main()` — wiring, dedup, CLI, logging

**Files:**
- Modify: `best_of_sno/scraper.py`
- Test: `best_of_sno/tests/test_main.py`

**Interfaces:**
- Consumes: every function above.
- Produces:
  - `run(data_dir: str, *, feed_url: str, dry_run: bool=False, no_rotate: bool=False, fetch=fetch_feed, now=None) -> dict` — the testable core; returns `{"moved_to_old": int, "new_found": int}`. `fetch`/`now` injectable for tests. Creates `data/` and `logs/` under `data_dir` if absent.
  - `main(argv=None) -> int` — `argparse` for `--dry-run`, `--no-rotate`, `--data-dir` (default `best_of_sno`), `--feed-url` (default `https://bestofsno.com/feed/`); configures logging to `logs/scraper.log`; calls `run`.

  Flow (spec §5.5): load_state → fetch → parse_items(scraped_at=now) → `fresh = [r for r in records if r["id"] not in seen_ids]` → unless `no_rotate`: `moved = rotate(...)` → `write_new(fresh)` → add fresh ids to seen, `last_run = now` → `save_state` **last**. `--dry-run`: do load/fetch/parse/dedup, log counts, write nothing.

- [ ] **Step 1: Write failing tests** in `test_main.py`, injecting `fetch` that returns the Task-2 fixture bytes and a fixed `now`, pointing `data_dir` at `tmp_path`:

```python
def test_first_run_fills_new_empty_old():
    res = run(tmp, feed_url="x", fetch=fake_fetch, now=NOW)
    assert res["new_found"] == 3 and new_rowcount == 3 and old_rowcount == 0
    assert state_json_exists
def test_second_run_same_feed_rotates_and_dedups():
    run(...); res2 = run(...)          # same fixture both times
    assert res2["new_found"] == 0      # all ids already seen
    assert res2["moved_to_old"] == 3   # first batch rotated to old
    assert new_rowcount == 0 and old_rowcount == 3
def test_dedup_skips_already_seen_guid():
    # second feed adds 1 brand-new item → only that one lands in new
def test_dry_run_writes_nothing():
    before = snapshot(tmp); run(..., dry_run=True); assert snapshot(tmp) == before
def test_no_rotate_keeps_old_untouched():
    run(...); run(..., no_rotate=True); assert old_rowcount unchanged
```

- [ ] **Step 2: Run, verify fail** → FAIL.
- [ ] **Step 3: Implement `run` then `main`** per the flow; `now` defaults to `datetime.now().astimezone().isoformat()`; log `moved_to_old` and `new_found`.
- [ ] **Step 4: Run, verify pass** — `pytest best_of_sno/tests/ -v` (whole suite) → PASS.
- [ ] **Step 5: Live smoke test** — `python -m best_of_sno.scraper --data-dir best_of_sno --dry-run` against the real feed; confirm it reports a sane `new_found` and writes nothing. Then one real run; confirm `new.csv` has rows incl. populated `source_site`.
- [ ] **Step 6: Commit** — `git commit -am "feat: main() wiring, dedup, CLI, logging"`.

---

## Notes for the executor

- `enrich()` (story-page fetch) and the category-page backfill are **explicitly deferred** (spec §6 / §5.1) — do not build them. The daily feed path is complete on its own.
- Do not create/install cron or launchd. After the suite passes and the smoke test works, the schedule line to hand the user is in spec §5.9.
- Keep `data/` and `logs/` out of git except for a `.gitkeep`; add a `.gitignore` for `best_of_sno/data/*.csv`, `best_of_sno/data/state.json`, `best_of_sno/logs/*.log` (fold this into Task 1's commit).
