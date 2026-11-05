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


# ---------- page-layout leftovers (advice model only) ----------
# A student's draft has none of these, so the advice model must not learn to
# comment on them. Layer 3 scores were made on the text before this step and
# are kept (re-scoring 733 stories takes hours, and this text barely bears
# on what the rubric measures).

_PLAYER_RE = re.compile(r"Your browser does not support the (?:video|audio) (?:tag|element)\.?")
_AUDIO_RE = re.compile(r"(?:[A-Z][\w’'-]+ ){1,3}Audio Clip(?: [–-] [A-Z][a-z]+ \d{1,2}, \d{4})?")
_PHOTO_CREDIT_RE = re.compile(
    r"\(?\b(?:Photos?|Graphics?|Videos?|Images?|Illustrations?|Art) "
    r"(?:courtesy(?: of)?|by|credit)\s*:?\s+[^.()“”\"]{1,60}?(?:\)|\.(?=\s|$)|$)")
# "( Jonathan Smith )": a credit line with spaces inside the brackets; two to
# four capitalized words, so "( DOGE )" stays.
_PAREN_CREDIT_RE = re.compile(r"\(\s(?:[A-Z][a-z][\w.’'-]*)(?:\s[A-Z][\w.’'-]*){1,3}\s\)")
_FLOURISH_RE = re.compile(r"(?<=[.!?”\"]) flourish (?=[“\"A-Z])")
# Drop caps split from their word ("T he", "E ven"). A, I and O are skipped:
# they are words on their own.
_DROPCAP_RE = re.compile(r"(^|[.!?\"”’] |[“\"])([B-HJ-NP-Z]) ([a-z]{2,})")
# A pull quote ends with " — Name" (optionally starred, for a changed name).
# Seen: "— Elina Mahanta*", "— chef Anthony Chevalier", "— Kerry Nickols,
# Heal the Bay Director of Science and Policy".
_PULLQUOTE_SIG_RE = re.compile(
    r"(?:^|[.!?”\"])\s*— (?:[a-z]+ )?[A-Z][\w’'.-]*\*?(?: [A-Z][\w’'.-]*\*?)?"
    r"(?:,(?: (?:[A-Z][\w’'.-]*|of|the|and|for|at))+)?")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?”\"])\s+")
_ATTRIBUTION_RE = re.compile(r"\b(?:said|says|explained|added|according)\b")
MIN_REPEAT_WORDS = 8


def _drop_repeats(text: str) -> tuple[str, int]:
    """Remove repeated sentences (pull quotes, captions that copy the text).

    One copy stays, picked by what follows it: an attribution ("said")
    within 120 characters counts for it; a pull-quote signature (" — Name")
    within 150, or a "( Name )" photo credit within 40, counts against it.
    Ties go to the first copy. A removed pull quote takes its " — Name"
    with it."""
    sents = [s for s in _SENT_SPLIT_RE.split(text) if len(s.split()) >= MIN_REPEAT_WORDS]
    removed = 0
    for s in dict.fromkeys(x for x in sents if sents.count(x) > 1):
        spots = [m.start() for m in re.finditer(re.escape(s), text)]
        if len(spots) < 2:
            continue

        def after(p, n):
            return text[p + len(s):p + len(s) + n]

        def score(p):
            return (bool(_ATTRIBUTION_RE.search(after(p, 120)))
                    - 2 * bool(_PULLQUOTE_SIG_RE.search(after(p, 150)))
                    - bool(_PAREN_CREDIT_RE.search(after(p, 40))))
        keep = max(spots, key=lambda p: (score(p), -p))
        for p in sorted((p for p in spots if p != keep), reverse=True):
            end = p + len(s)
            sig = _PULLQUOTE_SIG_RE.search(after(p, 150))
            if sig:
                end += sig.end()
            text = text[:p] + " " + text[end:]
            removed += 1
    return text, removed


MAX_CAPTION_WORDS = 40


def _drop_credits(text: str, pattern: re.Pattern) -> str:
    """Remove each photo credit and the caption sentence right before it
    (when that sentence is 4-40 words, with no quote marks and no "said")."""
    for m in reversed(list(pattern.finditer(text))):
        before = text[:m.start()].rstrip()
        cut = m.start()
        ends = [0] + [x.end() for x in _SENT_SPLIT_RE.finditer(before)]
        prev = before[ends[-1]:]
        if (4 <= len(prev.split()) <= MAX_CAPTION_WORDS and not re.search(r"[“”\"]", prev)
                and not _ATTRIBUTION_RE.search(prev)):
            cut = ends[-1]
        text = text[:cut] + " " + text[m.end():]
    return text


def _loose(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", s.lower().replace("’", "'").replace("'", ""))
    return _WS_RE.sub(" ", s).strip()


def _drop_pullquotes(text: str) -> tuple[str, int]:
    """Remove pull quotes: a run of sentences ending in " — Name" whose
    every sentence also appears elsewhere in the story (ignoring
    punctuation, so a quote split by "he said" still matches). A "— Name"
    quote found nowhere else is a quote box with its own words, and stays."""
    removed = 0
    for sig in reversed(list(re.finditer(r"(?<=[.!?”\"…])\s*— (?=(?:[a-z]+ )?[A-Z])", text))):
        before = text[:sig.start()]
        ends = [0] + [m.end() for m in _SENT_SPLIT_RE.finditer(before)]
        start = None
        for b in reversed(ends):
            chunk = before[b:start if start is not None else len(before)]
            words = _loose(chunk)
            if len(words.split()) < 3:
                break
            rest = _loose(text[:b] + " " + text[sig.start():])
            if words not in rest:
                break
            start = b
        if start is None:
            continue
        m = _PULLQUOTE_SIG_RE.match(text, sig.start() - 1 if sig.start() else 0)
        end = m.end() if m else sig.end()
        text = text[:start] + " " + text[end:]
        removed += 1
    return text, removed


def strip_layout(body: str | None) -> str:
    """Body text without video-player text, audio-clip labels, photo
    credits and their captions, embed labels, split drop caps, pull quotes
    and repeated sentences."""
    if not body:
        return ""
    text = _PLAYER_RE.sub(" ", body)
    text = _AUDIO_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    text = _drop_credits(text, _PHOTO_CREDIT_RE)
    text = _drop_credits(text, _PAREN_CREDIT_RE)
    text = _FLOURISH_RE.sub(" ", text)
    text = _DROPCAP_RE.sub(r"\1\2\3", text)
    text = _WS_RE.sub(" ", text).strip()
    text, _ = _drop_pullquotes(text)
    text, _ = _drop_repeats(text)
    return _WS_RE.sub(" ", text).strip()


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
