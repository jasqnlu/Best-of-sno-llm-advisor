"""Body-text evidence settles uncertain labels; offline relabel pass."""

import csv

import pytest

from best_of_sno.layer2 import (
    LAYER2_COLUMNS, UNCERTAIN_COLUMNS, body_overlap, classify, load_winner_corpus,
    main, normalize_title, relabel_uncertain, text_shingles,
)
from best_of_sno.scraper import COLUMNS

# Best of SNO's whole body for a podcast / long-form story (real, 35 words).
STUB = ("This story contains an alternate format that can only be viewed on the "
        "original site. View this story on Scot Scoop News . It was originally "
        "published on December 1, 2025 and was republished here on December 18, 2025.")


def _body(seed, n=120):
    return " ".join(f"w{seed}x{i}" for i in range(n))


def _w(title, body, **kw):
    w = {"id": "https://bestofsno.com/?p=1", "url": "https://bestofsno.com/1/a/b/",
         "title": title, "published": "2026-03-20", "author": "Ada Lee"}
    w.update(kw)
    w["norm_title"] = normalize_title(w["title"])
    w["shingles"] = text_shingles(body)
    return w


def _r(title, body, published="2026-03-03", author="Ada Lee"):
    return {"title": title, "published": published, "author": author, "body": body}


# --- overlap measure ---------------------------------------------------------

def test_identical_bodies_overlap_fully():
    assert body_overlap(text_shingles(_body(1)), text_shingles(_body(1))) == 1.0


def test_unrelated_bodies_do_not_overlap():
    assert body_overlap(text_shingles(_body(1)), text_shingles(_body(2))) == 0.0


def test_a_republish_with_small_edits_still_overlaps_highly():
    edited = _body(1).replace("w1x50", "changed", 1) + " an added closing line here"
    assert body_overlap(text_shingles(_body(1)), text_shingles(edited)) >= 0.9


def test_too_little_text_gives_no_verdict():
    # The Best of SNO stub and an empty school body carry no evidence.
    assert body_overlap(text_shingles(STUB), text_shingles(_body(1))) is None
    assert body_overlap(text_shingles(""), text_shingles(_body(1))) is None


# --- classify uses the body to settle what titles and bylines cannot ----------

def test_retitled_winner_with_the_same_body_is_a_winner():
    # Real case: "...her experience at MVHS" republished as "...at Monta Vista
    # High School" — title ratio 0.83, body overlap 0.97.
    v = classify(_r("Exchange student shares her experience at MVHS", _body(1)),
                 [_w("Exchange student shares her experience at Burlingame High School",
                     _body(1), id="EX")])
    assert v.label == "winner" and v.matched_id == "EX" and v.reason == ""


def test_same_author_different_body_is_a_non_winner():
    v = classify(_r("Food review: a new gelato shop", _body(2)),
                 [_w("AI misogyny and generative gender bias", _body(1))])
    assert v.label == "non_winner" and v.matched_id == ""


def test_stub_winner_body_stays_uncertain():
    v = classify(_r("Some other podcast episode", _body(2)),
                 [_w("The art of preservation: Fanmaking", STUB)])
    assert v.label == "uncertain" and v.reason == "author-date"


def test_empty_school_body_stays_uncertain():
    v = classify(_r("A photo gallery", ""),
                 [_w("A different story", _body(1))])
    assert v.label == "uncertain" and v.reason == "author-date"


def test_every_same_author_candidate_is_checked():
    winners = [_w("First winner", _body(1), id="A"),
               _w("Second winner", _body(2), id="B")]
    v = classify(_r("Retitled second winner", _body(2)), winners)
    assert v.label == "winner" and v.matched_id == "B"


def test_one_mismatch_and_one_unknown_stays_uncertain_on_the_unknown():
    winners = [_w("First winner", _body(1), id="A"),
               _w("Podcast winner", STUB, id="B")]
    v = classify(_r("Unrelated story", _body(3)), winners)
    assert v.label == "uncertain" and v.reason == "author-date" and v.matched_id == "B"


def test_near_title_with_the_same_body_is_a_winner():
    v = classify(_r("The art of preservation: Fanmakingg", _body(1), author="Zed Zhu"),
                 [_w("The art of preservation: Fanmaking", _body(1), id="F")])
    assert v.label == "winner" and v.matched_id == "F"


def test_near_title_with_a_different_body_is_a_non_winner():
    v = classify(_r("The art of preservation: Fanmakingg", _body(2), author="Zed Zhu"),
                 [_w("The art of preservation: Fanmaking", _body(1))])
    assert v.label == "non_winner"


def test_same_title_outside_the_lag_is_settled_by_the_body():
    # A recurring headline: dates alone cannot tell installments apart.
    win = _w("Humans of Carlmont", _body(1), id="H", published="2026-04-20")
    other = classify(_r("Humans of Carlmont", _body(2), published="2026-01-10"), [win])
    same = classify(_r("Humans of Carlmont", _body(1), published="2026-01-10"), [win])
    assert other.label == "non_winner"
    assert same.label == "winner" and same.matched_id == "H"


def test_records_without_a_body_key_behave_as_before():
    v = classify({"title": "Unrelated", "published": "2026-03-03", "author": "Ada Lee"},
                 [_w("A winner", _body(1))])
    assert v.label == "uncertain" and v.reason == "author-date"


# --- corpus keeps a fingerprint of each winner's body -------------------------

def _write(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_corpus_winners_carry_body_shingles(tmp_path):
    _write(tmp_path / "data" / "archive.csv",
           [{"id": "A", "title": "T", "school": "Carlmont High School", "body": _body(1)}],
           COLUMNS)
    w = load_winner_corpus(str(tmp_path))["Carlmont High School"][0]
    assert w["shingles"] == text_shingles(_body(1))
    assert "body" not in w


# --- relabel: re-judge uncertain.csv offline ----------------------------------

def _seed(tmp_path):
    school = "Burlingame High School"
    _write(tmp_path / "data" / "archive.csv", [
        {"id": "EX", "url": "https://bestofsno.com/9/f/ex/", "school": school,
         "title": "Exchange student shares her experience at Burlingame High School",
         "published": "2025-12-17", "author": "Ada Lee", "body": _body(1)},
        {"id": "POD", "url": "https://bestofsno.com/8/f/pod/", "school": school,
         "title": "A podcast", "published": "2025-12-17", "author": "Bo Chen",
         "body": STUB},
    ], COLUMNS)
    _write(tmp_path / "data" / "layer2.csv", [
        {"id": "https://theburlingameb.org/old/", "title": "Already labeled",
         "label": "non_winner", "source_site": "theburlingameb.org"},
    ], LAYER2_COLUMNS)

    def u(id_, title, body, author="Ada Lee"):
        return {"id": id_, "title": title, "body": body, "published": "2025-12-04",
                "author": author, "school": school, "source_site": "theburlingameb.org",
                "label": "uncertain", "matched_id": "EX", "reason": "author-date",
                "candidate_title": "x", "candidate_url": "y"}

    _write(tmp_path / "data" / "uncertain.csv", [
        u("https://theburlingameb.org/exchange/", "Exchange student shares her experience at MVHS",
          _body(1)),
        u("https://theburlingameb.org/climate/", "Climate change should not be political",
          _body(2)),
        # Bo Chen's only candidate is the podcast, whose stub decides nothing.
        u("https://theburlingameb.org/gallery/", "Photo gallery", "", author="Bo Chen"),
        {**u("https://theburlingameb.org/crossword/", "Crossword", ""), "published": "",
         "reason": "undated", "matched_id": ""},
    ], UNCERTAIN_COLUMNS)


def test_relabel_moves_settled_rows_and_keeps_the_rest(tmp_path):
    _seed(tmp_path)
    res = relabel_uncertain(str(tmp_path))
    assert res == {"winner": 1, "non_winner": 1, "uncertain": 2}

    labeled = {r["id"]: r for r in _read(tmp_path / "data" / "layer2.csv")}
    assert labeled["https://theburlingameb.org/exchange/"]["label"] == "winner"
    assert labeled["https://theburlingameb.org/exchange/"]["matched_id"] == "EX"
    assert labeled["https://theburlingameb.org/climate/"]["label"] == "non_winner"
    assert labeled["https://theburlingameb.org/climate/"]["matched_id"] == ""
    assert "https://theburlingameb.org/old/" in labeled  # existing rows kept
    assert list(_read(tmp_path / "data" / "layer2.csv")[0]) == LAYER2_COLUMNS

    left = {r["id"]: r for r in _read(tmp_path / "data" / "uncertain.csv")}
    assert set(left) == {"https://theburlingameb.org/gallery/", "https://theburlingameb.org/crossword/"}
    assert left["https://theburlingameb.org/gallery/"]["matched_id"] == "POD"
    assert left["https://theburlingameb.org/crossword/"]["reason"] == "undated"


def test_relabel_twice_changes_nothing_more(tmp_path):
    _seed(tmp_path)
    relabel_uncertain(str(tmp_path))
    before = ((tmp_path / "data" / "layer2.csv").read_text(),
              (tmp_path / "data" / "uncertain.csv").read_text())
    assert relabel_uncertain(str(tmp_path)) == {"winner": 0, "non_winner": 0, "uncertain": 2}
    after = ((tmp_path / "data" / "layer2.csv").read_text(),
             (tmp_path / "data" / "uncertain.csv").read_text())
    assert before == after


def test_relabel_does_not_duplicate_an_id_already_in_layer2(tmp_path):
    # A crash between the two writes leaves a moved row in both files; the
    # next relabel must not append it to layer2.csv a second time.
    _seed(tmp_path)
    rows = _read(tmp_path / "data" / "layer2.csv")
    rows.append({"id": "https://theburlingameb.org/climate/", "label": "non_winner"})
    _write(tmp_path / "data" / "layer2.csv", rows, LAYER2_COLUMNS)
    relabel_uncertain(str(tmp_path))
    ids = [r["id"] for r in _read(tmp_path / "data" / "layer2.csv")]
    assert ids.count("https://theburlingameb.org/climate/") == 1


def test_relabel_with_no_uncertain_file_is_a_no_op(tmp_path):
    assert relabel_uncertain(str(tmp_path)) == {"winner": 0, "non_winner": 0, "uncertain": 0}
    assert not (tmp_path / "data" / "layer2.csv").exists()


def test_main_relabel_runs_offline(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("network was used")

    monkeypatch.setattr("best_of_sno.backfill.fetch_all_post_sitemaps", boom)
    monkeypatch.setattr("best_of_sno.backfill.fetch_page", boom)
    _seed(tmp_path)
    assert main(["--data-dir", str(tmp_path), "--relabel"]) == 0
    assert len(_read(tmp_path / "data" / "uncertain.csv")) == 2


# --- a winner already matched to its own article ------------------------------

def test_author_date_candidate_already_claimed_is_ruled_out():
    # The winner's Best of SNO body is a stub, so the text can't decide; but
    # another article already matched it by exact title, so this
    # differently-titled one cannot be it.
    v = classify(_r("Some other podcast episode", _body(2)),
                 [_w("The art of preservation: Fanmaking", STUB, id="F")],
                 claimed={"F"})
    assert v.label == "non_winner"


def test_claimed_does_not_block_an_exact_title_match():
    # A second copy of a winner (a repost) must still be a winner, never a
    # negative.
    v = classify(_r("The art of preservation: Fanmaking", "", published="2026-01-01"),
                 [_w("The art of preservation: Fanmaking", STUB, id="F",
                     published="2026-01-05")],
                 claimed={"F"})
    assert v.label == "winner" and v.matched_id == "F"


def test_relabel_rules_out_winners_already_in_layer2(tmp_path):
    _seed(tmp_path)
    rows = _read(tmp_path / "data" / "layer2.csv")
    rows.append({"id": "https://theburlingameb.org/podcast/", "title": "A podcast",
                 "label": "winner", "matched_id": "POD", "source_site": "theburlingameb.org"})
    _write(tmp_path / "data" / "layer2.csv", rows, LAYER2_COLUMNS)
    res = relabel_uncertain(str(tmp_path))
    labeled = {r["id"]: r for r in _read(tmp_path / "data" / "layer2.csv")}
    assert labeled["https://theburlingameb.org/gallery/"]["label"] == "non_winner"
    assert res == {"winner": 1, "non_winner": 2, "uncertain": 1}
