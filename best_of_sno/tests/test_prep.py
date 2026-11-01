"""Tests for training-data prep: body cleanup and the training.csv build."""

import csv

from best_of_sno.layer2 import LAYER2_COLUMNS
from best_of_sno.prep import MIN_WORDS, build_training_set, clean_body

LONG = " ".join(["word"] * 40)


# --- clean_body -------------------------------------------------------------

def test_strips_ad_marker_wherever_it_appears():
    body = "Story continues below advertisement First line. Story continues below advertisement Second."
    assert clean_body(body) == "First line. Second."


def test_strips_leading_photo_credit():
    assert clean_body("Maddie Shoop-Gardner · The light in the dark Twenty-eight years") == \
        "The light in the dark Twenty-eight years"


def test_strips_lowercase_handle_credit():
    assert clean_body("harkeraquila · Super Bowl LX Predictions Listen") == "Super Bowl LX Predictions Listen"


def test_strips_credit_behind_a_stray_icon_glyph():
    assert clean_body("? Ashley Mitchell · Marissa Mayer Audio Clip Her heels click") == \
        "Marissa Mayer Audio Clip Her heels click"


def test_keeps_a_middle_dot_that_is_not_a_leading_credit():
    body = "The score was close. Fans cheered · the band played on."
    assert clean_body(body) == body


def test_does_not_treat_a_sentence_as_a_credit():
    body = "It rained all day, and nobody came. · Next item"
    assert clean_body(body) == body


def test_strips_escaped_html_tags():
    body = '&lt;br /&gt; College Map &lt;span data-mce-type="bookmark" style="x"&gt;&lt;/span&gt; by Claire'
    assert clean_body(body) == "College Map by Claire"


def test_clean_body_handles_empty():
    assert clean_body("") == ""
    assert clean_body(None) == ""


# --- build_training_set ------------------------------------------------------

def _row(id_, label, body, school="Carlmont High School"):
    r = {c: "" for c in LAYER2_COLUMNS}
    r.update(id=id_, url=f"https://x.org/{id_}/", title=id_, label=label, body=body,
             school=school, word_count=str(len(body.split())))
    return r


def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LAYER2_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_build_cleans_bodies_and_recounts_words(tmp_path):
    src, out = tmp_path / "layer2.csv", tmp_path / "training.csv"
    _write(src, [_row("a", "winner", "Story continues below advertisement " + LONG)])
    build_training_set(str(src), str(out))
    [row] = _read(out)
    assert "advertisement" not in row["body"]
    assert row["word_count"] == "40"


def test_build_drops_rows_under_min_words_after_cleaning(tmp_path):
    src, out = tmp_path / "layer2.csv", tmp_path / "training.csv"
    _write(src, [
        _row("keep", "non_winner", LONG),
        _row("crossword", "non_winner", "Created by Scot Center using PuzzleMe’s free cross word maker"),
        _row("empty", "non_winner", ""),
        # 4 words once the ad marker is gone, though 8 before
        _row("adonly", "non_winner", "Story continues below advertisement Half-off museums in February"),
    ])
    report = build_training_set(str(src), str(out))
    assert [r["id"] for r in _read(out)] == ["keep"]
    assert report["dropped_short"] == 3
    assert report["kept"] == {"non_winner": 1}


def test_build_keeps_only_winner_and_non_winner_labels(tmp_path):
    src, out = tmp_path / "layer2.csv", tmp_path / "training.csv"
    _write(src, [_row("w", "winner", LONG), _row("n", "non_winner", LONG), _row("u", "uncertain", LONG)])
    report = build_training_set(str(src), str(out))
    assert sorted(r["id"] for r in _read(out)) == ["n", "w"]
    assert report["dropped_label"] == 1


def test_build_output_has_the_layer2_columns(tmp_path):
    src, out = tmp_path / "layer2.csv", tmp_path / "training.csv"
    _write(src, [_row("w", "winner", LONG)])
    build_training_set(str(src), str(out))
    with open(out, newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == LAYER2_COLUMNS


def test_build_guards_a_body_that_starts_with_a_formula_after_cleaning(tmp_path):
    src, out = tmp_path / "layer2.csv", tmp_path / "training.csv"
    _write(src, [_row("w", "winner", "Jo Lee · =HYPERLINK(\"x\") " + LONG)])
    build_training_set(str(src), str(out))
    [row] = _read(out)
    assert row["body"].startswith("'=HYPERLINK")


def test_min_words_keeps_short_photo_essays():
    # Photo essays ("In Photos: ...") carry 20-80 words of intro and stay in.
    assert MIN_WORDS <= 20
