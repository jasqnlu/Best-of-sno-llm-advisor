"""Advice model: fix order, the pinned prompt, code checks, round-0 pick,
training export and the "Stories to learn from" picks. All offline."""

import json
import os

import pytest

from best_of_sno import advice as A
from best_of_sno.scorer import DIMENSION_KEYS

COEFS = {"lede": 0.07, "sourcing": -0.02, "quotes": 0.25, "focus": 0.25,
         "depth": -0.01, "significance": 0.01, "craft": 0.32}

BODY = ("On Friday, the district announced that custodian Ray Ortiz will retire after 31 years. "
        "Many students say he is the heart of the school. He has seen a lot of changes over the years. "
        "He still keys the boiler room door left-handed, the way his father taught him. "
        "“I never wanted to leave,” Ortiz said.")


def _story(**over):
    scores = {k: 4.0 for k in DIMENSION_KEYS}
    scores.update(lede=2.0, sourcing=2.0, depth=3.0, craft=5.0)
    s = {"id": "s1", "label": "non_winner", "source": "training", "school": "X",
         "title": "The last bell", "body": BODY, "word_count": 430, "scores": scores,
         "evidence": {k: "" for k in DIMENSION_KEYS}, "band": "Medium", "coefs": COEFS}
    s.update(over)
    return s


GOOD = """BIGGEST FIXES
1. Lede (2/5) — "On Friday, the district announced that custodian Ray Ortiz will retire after 31 years." This opens on news a
   district email already gave everyone. Open on a scene only you saw.
2. Sourcing (2/5) — "Many students say he is the heart of the school." Name two students and a coworker.
3. Depth (3/5) — "He has seen a lot of changes over the years." Name them: the year the gym flooded.

WHAT'S WORKING
Craft — "He still keys the boiler room door left-handed, the way his father taught him." A detail that shows who he is.

LENGTH
Under 500 words: in-depth features that win usually run longer.
"""


def test_fix_order_puts_the_biggest_gap_first_and_skips_fives():
    order = A.fix_order(_story()["scores"], COEFS)
    assert order[:3] == ["lede", "sourcing", "depth"]
    assert "craft" not in order


def test_weight_only_nudges_equal_gaps():
    scores = {k: 5.0 for k in DIMENSION_KEYS}
    scores.update(sourcing=3.0, craft=3.0)
    assert A.fix_order(scores, COEFS) == ["craft", "sourcing"]   # same gap: higher weight first
    scores.update(sourcing=1.0)
    assert A.fix_order(scores, COEFS)[0] == "sourcing"           # a big gap beats a big weight


def test_prompt_lists_inputs_and_fix_order():
    s = _story(evidence={**{k: "" for k in DIMENSION_KEYS}, "lede": "On Friday"})
    p = A.build_prompt(s)
    assert p.startswith(A.INSTRUCTIONS)
    assert "WORD COUNT: 430 (under 500)" in p
    assert '- Lede: 2/5 — "On Friday"' in p and "- Quotes: 4/5 — (no quote)" in p
    assert "FIX ORDER: Lede, Sourcing, Reporting depth" in p
    assert p.rstrip().endswith(BODY)


def test_averaged_scores_print_as_halves():
    assert A._fmt(4.0) == "4" and A._fmt(4.5) == "4.5"


def test_good_advice_passes():
    assert A.check_advice(GOOD, _story()) == []


def test_parse_accepts_the_short_dimension_name():
    p = A.parse_advice(GOOD)
    assert [f["dim"] for f in p["fixes"]] == ["lede", "sourcing", "depth"]
    assert p["working"]["dim"] == "craft"


@pytest.mark.parametrize("change, expected", [
    (lambda t: t.replace("heart of the school", "soul of the school"), "quote not in the draft"),
    (lambda t: t.replace("Sourcing (2/5)", "Sourcing (3/5)"), "score 3 but Sourcing is 2"),
    (lambda t: t.replace("1. Lede (2/5)", "1. Craft (5/5)"), "scored 5 or isn't in FIX ORDER"),
    (lambda t: t.replace("LENGTH\nUnder 500 words: in-depth features that win usually run longer.\n", ""),
     "LENGTH must be exactly"),
    (lambda t: t.replace("Name them:", "This has a 30% chance. Name them:"), "gives a percentage"),
    (lambda t: t.replace("Name them:", "See https://bestofsno.com/x. Name them:"), "contains a link"),
    (lambda t: t.replace("Name them:", "At 430 words it is short. Name them:"), "talks about length"),
    (lambda t: t.replace("WHAT'S WORKING\n", ""), "missing WHAT'S WORKING"),
    (lambda t: "Here is my advice.\n" + t, "text before the first heading"),
    (lambda t: t + "\nSTORIES TO LEARN FROM\n• x\n", "writes the stories part"),
])
def test_checks_catch_each_problem(change, expected):
    problems = A.check_advice(change(GOOD), _story())
    assert any(expected in p for p in problems), problems


def test_percent_or_word_count_inside_a_draft_quote_is_allowed():
    body = BODY + " The sale promised 50% off for the first 300 words of every essay."
    text = GOOD.replace('"He has seen a lot of changes over the years."',
                        '"The sale promised 50% off for the first 300 words of every essay."')
    assert A.check_advice(text, _story(body=body)) == []


def test_fixes_out_of_order_fail():
    lines = GOOD.split("\n")       # 0 heading, 1-2 lede fix, 3 sourcing fix, 4 depth fix
    swapped = [lines[0], lines[3].replace("2.", "1.", 1), lines[1].replace("1.", "2.", 1), lines[2]] + lines[4:]
    text = "\n".join(swapped)
    assert "fixes don't follow FIX ORDER" in A.check_advice(text, _story())


def test_long_draft_must_not_have_a_length_part():
    problems = A.check_advice(GOOD, _story(word_count=900))
    assert any("LENGTH part on a draft" in p for p in problems)
    ok = GOOD.split("LENGTH")[0]
    assert A.check_advice(ok, _story(word_count=900)) == []


def test_quote_with_inner_quotes_written_as_single_quotes_passes():
    text = GOOD.replace('"He still keys the boiler room door left-handed, the way his father taught him."',
                        '"\'I never wanted to leave,\' Ortiz said."')
    assert A.check_advice(text, _story()) == []


def test_all_fives_story():
    s = _story(scores={k: 5.0 for k in DIMENSION_KEYS}, word_count=900)
    text = f"BIGGEST FIXES\n{A.ALL_FIVES_LINE}\n\nWHAT'S WORKING\n" \
           'Craft — "He still keys the boiler room door left-handed" A telling detail.\n'
    assert A.check_advice(text, s) == []
    assert any("every score is 5" in p for p in A.check_advice(GOOD.split("LENGTH")[0], s))


def _stories():
    out = {}
    for i in range(40):
        label, source = [("non_winner", "training"), ("winner", "training"), ("winner", "archive"),
                         ("winner", "archive")][i % 4]
        out[f"id{i:02}"] = _story(id=f"id{i:02}", label=label, source=source,
                                  word_count=100 if i == 0 else 800)
    return out


def test_round0_pick_is_balanced_and_skips_held_out_and_stubs():
    st = _stories()
    ids = A.pick_round0(st, held={"id01", "id02"}, n=16)
    assert len(ids) == len(set(ids)) == 16
    assert not {"id00", "id01", "id02"} & set(ids)
    assert sum(st[i]["label"] != "winner" for i in ids) == 8
    assert sum(st[i]["source"] == "training" and st[i]["label"] == "winner" for i in ids) == 4
    assert ids == A.pick_round0(st, held={"id01", "id02"}, n=16)     # seeded


def _write_trial(tmp_path, ids):
    d = tmp_path / "data" / "layer3_trial"
    d.mkdir(parents=True)
    (d / "stories.csv").write_text("id,label\n" + "".join(f"{i},winner\n" for i in ids), encoding="utf-8")


def test_import_and_export_train(tmp_path, monkeypatch):
    st = {"s1": _story(), "s2": _story(id="s2", word_count=900)}
    monkeypatch.setattr(A, "load_stories", lambda d: st)
    _write_trial(tmp_path, ["held"])
    folder = tmp_path / "data" / "advice" / "round0"
    folder.mkdir(parents=True)
    (folder / "ids.json").write_text(json.dumps(["s1", "s2"]), encoding="utf-8")
    lines = [{"id": "s1", "advice": GOOD}, {"id": "s2", "advice": GOOD}, {"id": "zz", "advice": GOOD}]
    (folder / "out_1.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines) + "not json\n",
                                        encoding="utf-8")
    res = A.import_examples(str(tmp_path))
    assert res["passed"] == 1 and res["rejected"] == 1 and res["missing"] == 0
    assert len(res["file_problems"]) == 2                    # unknown id + bad JSON
    out = A.export_train(str(tmp_path))
    assert out["examples"] == 1
    rec = json.loads(open(out["path"], encoding="utf-8").readline())
    assert rec["messages"][0]["content"] == A.build_prompt(st["s1"])
    assert rec["messages"][1] == {"role": "assistant", "content": GOOD.strip()}


def test_export_train_refuses_held_out_stories(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "load_stories", lambda d: {"s1": _story()})
    _write_trial(tmp_path, ["s1"])
    folder = tmp_path / "data" / "advice" / "round0"
    folder.mkdir(parents=True)
    (folder / "examples.jsonl").write_text(json.dumps({"id": "s1", "advice": GOOD}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="held-out"):
        A.export_train(str(tmp_path))


def _winner(i, vec, **scores):
    base = {k: 4.0 for k in DIMENSION_KEYS}
    base.update(scores)
    return {"id": f"w{i}", "vector": vec, "scores": base, "title": f"Winner {i}",
            "school": "Carlmont High School", "published": "2026-01-05", "url": f"https://bestofsno.com/{i}/"}


def test_pick_takes_the_most_similar_five_for_each_fix():
    pool = [_winner(1, [1, 0], lede=4.0), _winner(2, [0.9, 0.1], lede=5.0),
            _winner(3, [0.8, 0.2], sourcing=5.0), _winner(4, [0, 1], lede=5.0, sourcing=5.0)]
    picks = A.pick_inspiration([1, 0], ["lede", "sourcing"], pool)
    assert [(p["id"], d) for p, d in picks] == [("w2", "lede"), ("w3", "sourcing")]


def test_pick_falls_back_to_the_best_nearby_and_never_repeats():
    pool = [_winner(1, [1, 0], lede=4.5), _winner(2, [0.9, 0.1], lede=3.0)]
    picks = A.pick_inspiration([1, 0], ["lede", "sourcing", "depth"], pool)
    assert [p["id"] for p, _ in picks] == ["w1", "w2"]
    assert picks[0][1] == "lede"


def test_pick_tops_up_to_two_when_there_is_one_fix_or_none():
    pool = [_winner(1, [1, 0], craft=5.0), _winner(2, [0.5, 0.5], quotes=5.0), _winner(3, [0, 1])]
    assert len(A.pick_inspiration([1, 0], ["craft"], pool)) == 2
    picks = A.pick_inspiration([1, 0], [], pool)
    assert [(p["id"], d) for p, d in picks] == [("w1", "craft"), ("w2", "quotes")]


def test_render_inspiration():
    text = A.render_inspiration([(_winner(1, [1], lede=5.0), "lede")])
    assert text.splitlines() == [
        "STORIES TO LEARN FROM",
        '• "Winner 1" — Carlmont High School — January 2026 — https://bestofsno.com/1/',
        "  Read for lede (5/5): " + A.ANCHORS["lede"][4],
    ]


def test_embed_is_resumable(tmp_path, monkeypatch):
    st = {f"s{i}": _story(id=f"s{i}") for i in range(20)}
    monkeypatch.setattr(A, "load_stories", lambda d: st)
    calls = []
    def fake(texts, model):
        calls.append(len(texts))
        return [[float(len(t))] for t in texts]
    assert A.embed(str(tmp_path), embedder=fake, log=lambda *_: None)["embedded"] == 20
    assert calls == [16, 4]
    assert A.embed(str(tmp_path), embedder=fake, log=lambda *_: None)["embedded"] == 0
    assert os.path.exists(A.embeddings_path(str(tmp_path)))


def test_embed_text_uses_title_and_opening():
    t = A.embed_text("T", " ".join(f"w{i}" for i in range(500)))
    assert t.startswith("T\n\nw0 ") and t.endswith(f"w{A.EMBED_WORDS - 1}")


def test_ollama_embed_checks_the_count():
    class R:
        def raise_for_status(self): pass
        def json(self): return {"embeddings": [[1.0]]}
    with pytest.raises(ValueError):
        A.ollama_embed(["a", "b"], post=lambda *a, **k: R())


def test_news_briefs_are_never_examples_or_picks():
    st = _stories()
    for i in ("id04", "id06"):
        st[i]["story_type"] = "news"
    assert not {"id04", "id06"} & set(A.pick_round0(st, held=set(), n=40))
    assert "id06" not in A.pool_ids(st, set()) and "id07" in A.pool_ids(st, set())


def test_layout_talk_fails():
    text = GOOD.replace("Name them:", "Cut the pull quote that repeats this. Name them:")
    assert "comments on page layout" in A.check_advice(text, _story())


def test_export_examples_skips_stories_done_in_earlier_rounds(tmp_path, monkeypatch):
    st = _stories()
    monkeypatch.setattr(A, "load_stories", lambda d: st)
    done = tmp_path / "data" / "advice" / "round0"
    done.mkdir(parents=True)
    (done / "examples.jsonl").write_text("".join(json.dumps({"id": f"id{i:02}", "advice": "x"}) + "\n"
                                                for i in range(1, 11)), encoding="utf-8")
    res = A.export_examples(str(tmp_path), n=100, round_name="round0b", skip_rounds=("round0",))
    ids = json.loads((tmp_path / "data" / "advice" / "round0b" / "ids.json").read_text(encoding="utf-8"))
    assert res["stories"] == 29 and not {f"id{i:02}" for i in range(1, 11)} & set(ids)
    with pytest.raises(ValueError):
        A.export_examples(str(tmp_path), round_name="round0", skip_rounds=("round0",))
