"""Advice-model training helpers: masking, fitting, split and padding,
tested with a fake word-level tokenizer (no torch, no downloads)."""

import json

import pytest

from best_of_sno import advice_train as T


class FakeTokenizer:
    """One id per whitespace word; the chat template mimics Gemma 4's."""
    def __init__(self):
        self.vocab = {}
        self.calls = []

    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        self.calls.append((tokenize, add_generation_prompt, enable_thinking))
        (m,) = messages
        return f"<bos> <|turn>user {m['content']} <turn|> <|turn>model <|channel>thought <channel|>"

    def __call__(self, text, add_special_tokens):
        assert add_special_tokens is False     # the template already has <bos>
        return {"input_ids": [self.vocab.setdefault(w, len(self.vocab) + 1) for w in text.split()]}


def _rec(i="s1", draft="Draft text here", advice="BIGGEST FIXES 1. fix it"):
    return {"id": i, "messages": [{"role": "user", "content": draft},
                                  {"role": "assistant", "content": advice}]}


def test_loss_is_on_the_advice_and_end_of_turn_only():
    tok = FakeTokenizer()
    ex = T.build_example(tok, _rec(advice="Fix the lede now <turn|>".replace(" <turn|>", "")))
    n_prompt = len("<bos> <|turn>user Draft text here <turn|> <|turn>model <|channel>thought <channel|>".split())
    assert ex["labels"][:n_prompt] == [T.IGNORE] * n_prompt
    target = ex["labels"][n_prompt:]
    assert len(target) == len("Fix the lede now<turn|>".split())   # end-of-turn joins the last word
    assert target == ex["input_ids"][n_prompt:]
    assert len(ex["input_ids"]) == len(ex["attention_mask"]) == len(ex["labels"])
    assert tok.calls == [(False, True, False)]                    # thinking off, generation prompt


def test_too_long_examples_are_dropped_not_cut():
    tok = FakeTokenizer()
    assert T.build_example(tok, _rec(draft="word " * 50), max_len=20) is None
    kept, too_long = T.build_all(tok, [_rec("a"), _rec("b", draft="word " * 50)], max_len=20)
    assert len(kept) == 1 and too_long == ["b"]


def test_wrong_roles_fail():
    bad = {"id": "x", "messages": [{"role": "assistant", "content": "a"}]}
    with pytest.raises(ValueError):
        T.build_example(FakeTokenizer(), bad)


def test_split_is_seeded_and_disjoint():
    recs = [_rec(f"id{i:03}") for i in range(299)]
    tr, va = T.split(recs)
    assert len(va) == 15 and len(tr) == 284
    assert not {r["id"] for r in tr} & {r["id"] for r in va}
    assert {r["id"] for r in va} == {r["id"] for r in T.split(list(reversed(recs)))[1]}


def test_pad_batch_masks_padding():
    b = T.pad_batch([{"input_ids": [1, 2, 3], "attention_mask": [1, 1, 1], "labels": [-100, 2, 3]},
                     {"input_ids": [4], "attention_mask": [1], "labels": [4]}], pad_id=0)
    assert b["input_ids"][1] == [4, 0, 0]
    assert b["attention_mask"][1] == [1, 0, 0]
    assert b["labels"][1] == [4, -100, -100]


def test_check_file(tmp_path):
    p = tmp_path / "train.jsonl"
    recs = [_rec("a"), _rec("b", draft="word " * 7000), {"id": "c", "messages": []}]
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    res = T.check_file(str(p), held_ids={"a"})
    assert res["examples"] == 3 and res["held_out_leaked"] == ["a"]
    assert res["est_over_max_len"] == 1 and len(res["shape_problems"]) == 1
