"""Tests for title normalization + the three-way labeler (Layer 2, Task 3)."""

from best_of_sno.layer2 import NEARMATCH_RATIO, classify, normalize_title


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
    v = classify(_r("A completely unrelated headline", author="Zed Zhu"),
                 [_w("Don’t Look Away")])
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
    # A different author keeps the author+date rule out of it, so only the
    # title threshold decides.
    v = classify(_r("The art of preservation: Glass eye making", author="Zed Zhu",
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


def test_author_date_rule_sees_through_a_staff_role_in_the_byline():
    # Real Harker byline: the role contains " and ", so parse_byline keeps
    # the whole string as the author. The winner's clean name must still match.
    v = classify(_r("Reworded headline", author="Liana Barooah , Sports and Photo Editor"),
                 [_w("Original headline", author="Liana Barooah")])
    assert v.label == "uncertain" and v.reason == "author-date"


def test_author_match_is_whole_name_not_substring():
    v = classify(_r("Reworded headline", author="Sam Lin"),
                 [_w("Original headline", author="Sam Li")])
    assert v.label == "non_winner"


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


def test_single_exact_title_with_different_author_and_date_is_uncertain():
    # A recurring headline: one installment won, this is a different one.
    # It must not become a false-positive winner (spec §8), nor a negative.
    v = classify(_r("Humans of Carlmont", author="Zed Zhu", published="2026-09-09"),
                 [_w("Humans of Carlmont", author="May Lin", published="2026-04-01")])
    assert v.label == "uncertain" and v.reason == "title-ambiguous"


def test_single_exact_title_with_same_author_but_shifted_date_is_a_winner():
    v = classify(_r("Don’t Look Away", published="2026-03-04"),
                 [_w("Don’t Look Away", published="2026-03-03")])
    assert v.label == "winner"


def test_single_exact_title_with_same_date_but_other_byline_is_a_winner():
    v = classify(_r("Don’t Look Away", author="The Editorial Board"),
                 [_w("Don’t Look Away", author="Staff")])
    assert v.label == "winner"


def test_author_date_rule_allows_the_republish_lag():
    # Measured on real Carlmont winners: Best of SNO republishes 3-40 days
    # after the school (school 2026-02-27 -> SNO 2026-03-27). A reworded
    # winner must still be surfaced, not filed as a non_winner.
    v = classify(_r("Energy drinks: how students power through", published="2026-02-27"),
                 [_w("Energy culture: How students are powering through",
                     published="2026-03-27")])
    assert v.label == "uncertain" and v.reason == "author-date"


def test_republish_before_the_school_date_does_not_corroborate():
    v = classify(_r("Reworded headline", published="2026-03-10"),
                 [_w("Original headline", published="2026-03-01")])
    assert v.label == "non_winner"


def test_lag_beyond_the_window_does_not_corroborate():
    v = classify(_r("Reworded headline", published="2026-03-01"),
                 [_w("Original headline", published="2026-06-01")])  # 92 days
    assert v.label == "non_winner"


def test_same_titled_installment_outside_the_lag_window_is_uncertain():
    # A recurring column by the same writer: the installment that won was
    # republished 2026-04-20, this one ran in January. Same author is not
    # enough — only an installment whose dates fit the republish lag can be
    # the winning one.
    v = classify(_r("Humans of Carlmont", published="2026-01-10"),
                 [_w("Humans of Carlmont", published="2026-04-20")])
    assert v.label == "uncertain" and v.reason == "title-ambiguous"
