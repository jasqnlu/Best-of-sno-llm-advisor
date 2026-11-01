"""Training-data prep: turn layer2.csv into training.csv.

These are cleanups for the model, not scraper fixes, so layer2.csv stays as
crawled and this step can be rerun at any time. Each cleanup removes text
that marks where a story came from rather than how well it is written:

- "Story continues below advertisement": in 1,861 of 1,862 Best of SNO
  bodies but only Torrey Pines' school pages.
- A leading "Name · " photo credit: Carlmont's long-form template opens
  with one, and more winners are long-form (13 of 81 winners vs 14 of
  1,710 non-winners on 2026-11-01).
- Escaped HTML tags (``&lt;br /&gt;``) left in a handful of bodies.

Rows under MIN_WORDS after cleaning are dropped: crosswords, trivia,
sudoku, galleries, issue PDFs. Every winner runs 100+ words. Only winner
and non_winner rows are kept; uncertain.csv is never read, so it stays
held out.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from collections import Counter

from .layer2 import LAYER2_COLUMNS, _rows_to_csv_text
from .scraper import word_count

# Photo essays ("In Photos: ...") carry 20-80 words of intro and stay in;
# crosswords, trivia and galleries run 0-19.
MIN_WORDS = 20
LABELS = ("winner", "non_winner")

_AD_RE = re.compile(r"Story continues below advertisement")
# 1-6 words before the dot, no sentence punctuation: a name or a handle,
# optionally behind a stray icon glyph that rendered as "?".
_CREDIT_RE = re.compile(r"^(?:\W+ )?(?:[^\s·.!?,;:]+ ){0,5}[^\s·.!?,;:]+ · ")
_ESCAPED_TAG_RE = re.compile(r"&lt;/?[A-Za-z][^<>]*?&gt;")
_WS_RE = re.compile(r"\s+")


def clean_body(body: str | None) -> str:
    """Body text with source-specific markers removed, whitespace collapsed."""
    if not body:
        return ""
    text = _AD_RE.sub(" ", body)
    text = _ESCAPED_TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return _CREDIT_RE.sub("", text, count=1)


def build_training_set(layer2_path: str, out_path: str) -> dict:
    """Write cleaned winner/non_winner rows to ``out_path``; return a report."""
    # sys.maxsize would overflow a C long on Windows; 2**31 - 1 fits everywhere.
    csv.field_size_limit(2**31 - 1)
    kept: Counter = Counter()
    dropped_label = dropped_short = 0
    rows = []
    with open(layer2_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("label") not in LABELS:
                dropped_label += 1
                continue
            row["body"] = clean_body(row.get("body"))
            row["word_count"] = str(word_count(row["body"]))
            if int(row["word_count"]) < MIN_WORDS:
                dropped_short += 1
                continue
            kept[row["label"]] += 1
            rows.append(row)

    # The shared writer guards each cell against spreadsheet formulas, which
    # matters here: stripping a credit can leave a body starting with "=".
    tmp = out_path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.write(_rows_to_csv_text(rows, LAYER2_COLUMNS))
    os.replace(tmp, out_path)
    return {"kept": dict(kept), "dropped_short": dropped_short, "dropped_label": dropped_label}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build training.csv from layer2.csv")
    parser.add_argument("--data-dir", default="best_of_sno", help="folder holding data/")
    args = parser.parse_args(argv)
    data = os.path.join(args.data_dir, "data")
    report = build_training_set(os.path.join(data, "layer2.csv"), os.path.join(data, "training.csv"))
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
