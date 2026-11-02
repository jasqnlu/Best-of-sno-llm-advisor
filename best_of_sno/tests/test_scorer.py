"""Layer 3 scorer: rubric prompt, reply validation, pinned Ollama call."""

import json

import pytest

from best_of_sno.scorer import (
    DIMENSION_KEYS, OLLAMA_OPTIONS, build_prompt, evidence_found, long_enough,
    parse_scores, response_schema, rubric_text, score_with_ollama,
)


def _reply(**over):
    data = {k: {"score": 3, "evidence": "a quote"} for k in DIMENSION_KEYS}
    data["story_type"] = "feature"
    data.update(over)
    return data


def test_rubric_names_all_seven_dimensions_with_five_anchors():
    text = rubric_text()
    assert len(DIMENSION_KEYS) == 7
    for key in DIMENSION_KEYS:
        assert f"({key})" in text
    assert text.count("\n5. ") == 7


def test_prompt_puts_the_story_after_the_rubric():
    p = build_prompt("Title here", "Body here")
    assert p.startswith(rubric_text())
    assert p.endswith("TITLE: Title here\n\nSTORY:\nBody here")


def test_schema_requires_every_dimension_and_story_type():
    assert set(response_schema()["required"]) == set(DIMENSION_KEYS) | {"story_type"}


def test_parse_accepts_a_valid_reply_and_strips_code_fences():
    out = parse_scores("```json\n" + json.dumps(_reply()) + "\n```")
    assert out["lede"] == {"score": 3, "evidence": "a quote"}
    assert out["story_type"] == "feature"


@pytest.mark.parametrize("bad", [
    "not json",
    json.dumps([1, 2]),
    json.dumps({k: v for k, v in _reply().items() if k != "craft"}),
    json.dumps(_reply(lede={"score": 6, "evidence": ""})),
    json.dumps(_reply(lede={"score": True, "evidence": ""})),
    json.dumps(_reply(lede={"score": "4", "evidence": ""})),
    json.dumps(_reply(story_type="essay")),
])
def test_parse_rejects_malformed_replies(bad):
    with pytest.raises(ValueError):
        parse_scores(bad)


def test_length_check_is_500_words():
    assert not long_enough(499)
    assert long_enough(500)


def test_evidence_must_appear_in_the_story_ignoring_punctuation_and_case():
    body = "“We lost everything,” she said. The fire spread fast."
    assert evidence_found('"We lost everything," she said', body)
    assert evidence_found("the fire spread fast", body)
    assert not evidence_found("We lost it all", body)
    assert not evidence_found("", body)


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_ollama_call_is_pinned_and_parses_the_reply():
    sent = {}

    def post(url, json, timeout):
        sent.update(json)
        return _Resp({"prompt_eval_count": 1000,
                      "message": {"content": __import__("json").dumps(_reply())}})

    out = score_with_ollama("gemma4:e4b", "T", "B", post=post)
    assert sent["think"] is False
    assert sent["options"] == OLLAMA_OPTIONS and OLLAMA_OPTIONS["temperature"] == 0
    assert sent["format"] == response_schema()
    assert out["scores"]["story_type"] == "feature"
    assert "error" not in out


def test_ollama_call_flags_a_prompt_that_fills_the_context():
    post = lambda url, json, timeout: _Resp(
        {"prompt_eval_count": OLLAMA_OPTIONS["num_ctx"], "message": {"content": "{}"}})
    out = score_with_ollama("m", "T", "B", post=post)
    assert "context window" in out["error"] and "scores" not in out


def test_ollama_call_records_a_bad_reply_as_an_error():
    post = lambda url, json, timeout: _Resp({"prompt_eval_count": 10, "message": {"content": "nope"}})
    out = score_with_ollama("m", "T", "B", post=post)
    assert out["error"].startswith("not JSON") and out["raw"] == "nope"
