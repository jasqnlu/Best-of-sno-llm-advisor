"""Clean the winners corpus's ``source_site`` column, offline.

    python -m best_of_sno.sources          # rewrite source_site, write school_sites.csv
    python -m best_of_sno.sources --dry-run

``source_site`` is guessed from image hosts in each story (see
``scraper.extract_source_site``), so it is noisy: chart embeds such as
Flourish show up as the "school", and a story without images gets a blank.
Raw story HTML isn't kept, so the guess can't be re-run; instead the school
name, which comes from the byline and is reliable, settles it:

1. drop hosts that are never a school: chart embeds and the platform
   (``scraper._PLATFORM_HOST_SUFFIXES``, which new scrapes also skip);
2. for each named school, the most common remaining host is its site, and
   every row of that school gets it (filling blanks);
3. a school whose top two hosts tie keeps each row's own value and is
   reported, since there is no way to tell which is right.

Rows with no school name keep their own (cleaned) host. The result also
goes to ``data/school_sites.csv``: one row per school with its site and
winner count, which is what picking new schools to crawl needs. That file
holds only names and counts, no story text, but stays in the git-ignored
data folder with everything else.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
from collections import Counter, defaultdict

from . import scraper

CORPUS_FILES = ("archive.csv", "new.csv", "old.csv")
SCHOOL_SITES_COLUMNS = ["school", "site", "winners", "rows_with_site_before", "status"]


def _not_school(host: str) -> bool:
    return scraper._is_platform_host(host)


def school_sites(rows: list[dict]) -> dict[str, dict]:
    """``{school: {"site", "winners", "rows_with_site_before", "status"}}``.

    status is ``agreed`` (one host), ``majority`` (more than one, a clear
    winner), ``tie`` (no site chosen) or ``unknown`` (no usable host)."""
    hosts: dict[str, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    before: Counter = Counter()
    for r in rows:
        school = r.get("school", "").strip()
        if not school:
            continue
        total[school] += 1
        host = r.get("source_site", "").strip().lower()
        if host:
            before[school] += 1
        if host and not _not_school(host):
            hosts[school][host] += 1
    out = {}
    for school in total:
        top = hosts[school].most_common(2)
        if not top:
            site, status = "", "unknown"
        elif len(top) == 2 and top[0][1] == top[1][1]:
            site, status = "", "tie"
        else:
            site, status = top[0][0], "agreed" if len(hosts[school]) == 1 else "majority"
        out[school] = {"site": site, "winners": total[school],
                       "rows_with_site_before": before[school], "status": status}
    return out


def clean_rows(rows: list[dict], sites: dict[str, dict]) -> Counter:
    """Set each row's ``source_site`` in place; return what changed."""
    changes: Counter = Counter()
    for r in rows:
        old = r.get("source_site", "")
        new = "" if _not_school(old.strip().lower()) else old
        school = r.get("school", "").strip()
        if school and sites.get(school, {}).get("site"):
            new = sites[school]["site"]
        if new != old:
            changes["filled" if not old else "cleared" if not new else "replaced"] += 1
        r["source_site"] = new
    return changes


def run(data_dir: str, *, dry_run: bool = False) -> dict:
    data = os.path.join(data_dir, "data")
    files = {name: scraper._read_rows(os.path.join(data, name)) for name in CORPUS_FILES
             if os.path.exists(os.path.join(data, name))}
    every = [r for rows in files.values() for r in rows]
    sites = school_sites(every)
    report = {"rows": len(every), "blank_before": sum(not r.get("source_site") for r in every)}
    changes: Counter = Counter()
    for name, rows in files.items():
        changes += clean_rows(rows, sites)
        if not dry_run:
            scraper._atomic_write_text(os.path.join(data, name), scraper._rows_to_csv_text(rows))
    report["blank_after"] = sum(not r.get("source_site") for r in every)
    report["changes"] = dict(changes)
    report["schools"] = dict(Counter(s["status"] for s in sites.values()))
    report["ties"] = sorted(k for k, v in sites.items() if v["status"] == "tie")
    if not dry_run:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=SCHOOL_SITES_COLUMNS)
        w.writeheader()
        for school, s in sorted(sites.items(), key=lambda kv: (-kv[1]["winners"], kv[0])):
            w.writerow({"school": school, **s})
        scraper._atomic_write_text(os.path.join(data, "school_sites.csv"), buf.getvalue())
    return report


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    a = p.parse_args(argv)
    print(run(a.data_dir, dry_run=a.dry_run))


if __name__ == "__main__":
    main()
