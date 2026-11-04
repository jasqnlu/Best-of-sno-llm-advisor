"""Layer 3 scorer: grade one story on seven 1–5 dimensions.

The rubric (dimension names and anchor tables) is the one the owner approved
on 2026-11-01; see docs/layer3-brainstorm-context.md section 4. Every story,
training or draft, must go through the same pinned setup (model, prompt,
OLLAMA_OPTIONS, thinking off) or the Layer 4 chance bar drifts.

Length is not graded here: ``long_enough`` is a plain word-count check.
"""

from __future__ import annotations

import json
import re
import time

import requests

LENGTH_THRESHOLD = 500

STORY_TYPES = ["feature", "news", "sports", "opinion", "profile", "review", "other"]

# (key, label, what it measures, anchors for 1..5)
DIMENSIONS = [
    ("lede", "Lede", "the opening pulls you in and points at the stakes", [
        'Generic opening ("On Tuesday, the school board met..."); nothing to pull you in.',
        "States the topic but no hook or stakes.",
        "A decent hook, but the stakes come a few paragraphs later.",
        "Strong hook; stakes clear in the first paragraph or two.",
        "A specific detail or scene you'd remember that leads straight into why the story matters.",
    ]),
    ("sourcing", "Sourcing", "people with a direct stake; a range of viewpoints; named over anonymous", [
        'No sources, or only unnamed "students say" / the writer\'s own view.',
        "One or two sources, mostly bystanders or officials restating facts; no one with a direct stake.",
        "Some people with a direct stake, but one viewpoint dominates or a key affected group is missing.",
        "Several named people with a direct stake, and more than one viewpoint.",
        "The people most affected are at the center, named, plus the other views needed to see the whole story (including those who disagree or hold power).",
    ]),
    ("quotes", "Quotes", "quotes reveal feeling or insight the writer couldn't paraphrase, not logistics", [
        'No quotes, or quotes only give logistics ("The event starts at 7 p.m.").',
        "Quotes mostly repeat facts the writer could have paraphrased.",
        "A mix: a few quotes show feeling or insight; the rest are filler.",
        "Most quotes reveal feeling, insight or the speaker's voice; little filler.",
        "At least one quote you'd remember that only that person could have said; every quote earns its place.",
    ]),
    ("focus", "Focus", "stays on one angle; every section serves it", [
        "No clear angle; a list of facts or events.",
        "An angle exists, but the story wanders into unrelated sections.",
        "Mostly on one angle, with one or two sections that drift.",
        "Clear angle; nearly every section serves it.",
        "One sharp angle; every section builds on it and nothing could be cut without loss.",
    ]),
    ("depth", "Reporting depth", "facts, data, documents, scenes beyond interviews", [
        "Only the writer's opinion, or a single interview.",
        "Interviews only; no facts, numbers or context beyond what sources said.",
        "Interviews plus some facts, numbers or background.",
        "Interviews backed by data, documents or scenes the writer saw firsthand.",
        "Original reporting: documents, data and firsthand scenes combined to show something readers didn't know.",
    ]),
    ("significance", "Significance", "why readers should care; stakes beyond the school", [
        "No reason given for readers to care.",
        "The topic matters to a few people, and the story doesn't explain why.",
        "Says why it matters, but only within the school.",
        "Clear stakes for readers, with real consequences shown.",
        "Ties the stakes to a wider issue beyond the school; readers finish knowing why it matters.",
    ]),
    ("craft", "Craft", "clear sentences, flow between sections, a real ending", [
        "Hard to follow; frequent errors.",
        "Readable but choppy; sections don't connect; ends abruptly.",
        "Clear sentences; some rough transitions; the ending just summarizes.",
        "Smooth flow, clear sentences and a deliberate ending.",
        "Polished writing with a voice; transitions carry the reader; the ending lands (a callback, an image or a quote that resonates).",
    ]),
]
DIMENSION_KEYS = [d[0] for d in DIMENSIONS]

# Candidate rewordings, tried on the 60-story trial before any change to the
# pinned rubric above. A variant swaps one dimension's "what" and anchors;
# the scores file name carries the variant so runs never mix.
VARIANTS = {
    # Focus v1 gives nearly every story a 4 and barely tracks Claude (rank
    # agreement 0.11 on the trial). v2 asks for a stated central point and
    # sections that move it forward, so a 4 has to be earned.
    "focus-v2": {"focus": (
        "a central point stated early (a nut graf), and sections that move it forward instead of just adding facts", [
            "Covers a topic, not a story: you couldn't state its point in one sentence.",
            "A point can be guessed, but the story never states it; sections read as separate pieces on the same topic.",
            "The point is stated, but late (after the first five paragraphs) or vaguely; several sections add facts without moving it forward.",
            "The point is stated early and most sections add something new to it, but at least one section could be cut with little loss.",
            "A sharp point stated early; every section moves it forward with new evidence, a turn or a complication, and nothing could be cut without loss.",
        ])},
}


def dimensions(variant: str | None = None) -> list[tuple]:
    """The rubric's dimensions, with ``variant``'s swaps applied."""
    swaps = VARIANTS[variant] if variant else {}
    return [(k, label, *swaps[k]) if k in swaps else (k, label, what, anchors)
            for k, label, what, anchors in DIMENSIONS]

# Pinned Ollama settings. num_ctx 8192 fits the longest training feature
# (~6k tokens) and keeps gemma4:12b fully on the 8 GB RTX 2060 Super.
OLLAMA_OPTIONS = {"temperature": 0, "seed": 0, "num_ctx": 8192}
OLLAMA_URL = "http://localhost:11434/api/chat"


def rubric_text(variant: str | None = None) -> str:
    """The instructions every scorer gets, word for word."""
    lines = [
        "You are grading a student journalism story for a high school newsroom.",
        "Score it on each of the seven dimensions below from 1 to 5, using the",
        "anchor descriptions. Judge only the writing and reporting; ignore the",
        "story's length, topic popularity and the school it comes from.",
        "For each dimension also give one short exact quote (under 25 words)",
        "copied from the story that best supports the score.",
        "Then tag the story type as one of: " + ", ".join(STORY_TYPES) + ".",
        "",
    ]
    for key, label, what, anchors in dimensions(variant):
        lines.append(f"## {label} ({key}): {what}")
        lines.extend(f"{i}. {text}" for i, text in enumerate(anchors, start=1))
        lines.append("")
    example = {k: {"score": 3, "evidence": "..."} for k in DIMENSION_KEYS}
    example["story_type"] = "feature"
    lines.append("Reply with JSON only, exactly this shape:")
    lines.append(json.dumps(example))
    return "\n".join(lines)


def build_prompt(title: str, body: str, variant: str | None = None) -> str:
    return f"{rubric_text(variant)}\n\nTITLE: {title}\n\nSTORY:\n{body}"


def response_schema() -> dict:
    """JSON schema passed to Ollama's ``format`` so the reply has every field."""
    dim = {"type": "object",
           "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5},
                          "evidence": {"type": "string"}},
           "required": ["score", "evidence"]}
    props = {k: dim for k in DIMENSION_KEYS}
    props["story_type"] = {"type": "string", "enum": STORY_TYPES}
    return {"type": "object", "properties": props, "required": DIMENSION_KEYS + ["story_type"]}


def parse_scores(text: str) -> dict:
    """Validate a scorer reply; return ``{dim: {score, evidence}, story_type}``.

    Raises ValueError on anything malformed, so a bad reply is recorded as
    an error instead of silently becoming a score."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    out = {}
    for key in DIMENSION_KEYS:
        item = data.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"missing {key}")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError(f"{key} score out of range: {score!r}")
        out[key] = {"score": score, "evidence": str(item.get("evidence", "")).strip()}
    story_type = data.get("story_type")
    if story_type not in STORY_TYPES:
        raise ValueError(f"bad story_type: {story_type!r}")
    out["story_type"] = story_type
    return out


def long_enough(word_count: int) -> bool:
    return word_count >= LENGTH_THRESHOLD


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[\"'.,;:!?()\[\]—–-]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def evidence_found(evidence: str, body: str) -> bool:
    """True when the evidence quote really is in the story (ignoring
    punctuation, case and curly quotes); a check on made-up quotes."""
    ev = _norm(evidence)
    return bool(ev) and ev in _norm(body)


def score_with_ollama(model: str, title: str, body: str, *, variant: str | None = None,
                      post=requests.post) -> dict:
    """Score one story with the pinned Ollama setup.

    Returns ``{"scores": ..., "prompt_tokens", "seconds"}`` or
    ``{"error": ..., ...}``. Raises if the prompt would not fit in num_ctx,
    because Ollama silently cuts the front of an over-long prompt."""
    payload = {
        "model": model, "stream": False, "think": False,
        "format": response_schema(), "options": OLLAMA_OPTIONS,
        "messages": [{"role": "user", "content": build_prompt(title, body, variant)}],
    }
    start = time.time()
    resp = post(OLLAMA_URL, json=payload, timeout=1800)
    resp.raise_for_status()
    reply = resp.json()
    result = {"prompt_tokens": reply.get("prompt_eval_count"),
              "seconds": round(time.time() - start, 2)}
    if (result["prompt_tokens"] or 0) >= OLLAMA_OPTIONS["num_ctx"]:
        result["error"] = "prompt filled the context window; story may be cut"
        return result
    try:
        result["scores"] = parse_scores(reply["message"]["content"])
    except ValueError as e:
        result["error"] = str(e)
        result["raw"] = reply["message"]["content"][:2000]
    return result
