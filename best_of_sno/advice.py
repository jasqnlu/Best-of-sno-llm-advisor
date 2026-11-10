"""Advice model: the pinned prompt, round-0 examples, code checks, the
training export for Colab, and the "Stories to learn from" picks.

    python -m best_of_sno.advice show ID                 # the pinned prompt for one story
    python -m best_of_sno.advice export-examples --n 100 # batches for Claude subagents
    python -m best_of_sno.advice import                  # check the subagents' advice
    python -m best_of_sno.advice export-train            # chat JSONL for Colab
    python -m best_of_sno.advice check-train             # check it before uploading
    python -m best_of_sno.advice embed                   # cache embeddings (Ollama)
    python -m best_of_sno.advice inspire ID              # "Stories to learn from" for one story

Design: docs/superpowers/specs/2026-11-03-advice-model-design.md.

The model writes three parts (BIGGEST FIXES, WHAT'S WORKING, LENGTH);
code adds the fourth (STORIES TO LEARN FROM), so every link is a real
winner. Everything here that holds story text is written to
best_of_sno/data/advice/ (git-ignored).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re

import requests

from .layer3 import feature_set, scores_file
from .layer3_trial import _read_csv, load_scores, trial_dir
from .layer4 import chance_band, predict
from .prep import strip_layout
from .scraper import word_count
from .scorer import DIMENSION_KEYS, DIMENSIONS, LENGTH_THRESHOLD, evidence_found

SCORER_MODEL = "gemma4:12b"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"

MAX_FIXES = 3
MAX_QUOTE_WORDS = 25
LENGTH_LINE = "Under 500 words: in-depth features that win usually run longer."
ALL_FIVES_LINE = "None: every dimension scored 5."
BATCH_SIZE = 25
ROUND0_N = 100
SEED = 20261104
EMBED_WORDS = 300          # title + this many opening words are embedded
EMBED_BATCH = 16
FALLBACK_POOL = 20         # if no similar winner scored 5, look this deep
MIN_PICKS, MAX_PICKS = 2, 3
WEIGHT_NUDGE = (0.75, 1.25)
MIN_WORDS = 150            # shorter "stories" are stubs; never examples or picks
# Scorer story types the advice model learns from and recommends. News
# briefs, Q&A transcripts and the like (tagged news/other/...) are left out.
ADVICE_TYPES = ("feature", "profile")

LABELS = {k: label for k, label, _, _ in DIMENSIONS}
ANCHORS = {k: anchors for k, _, _, anchors in DIMENSIONS}
# A fix may name a dimension by its label ("Reporting depth"), its key
# ("depth") or the label's last word ("Depth").
_NAMES = {}
for _k, _label in LABELS.items():
    _NAMES[_label.lower()] = _NAMES[_k] = _NAMES[_label.split()[-1].lower()] = _k

INSTRUCTIONS = f"""You are a writing coach for a high school newsroom. A student's in-depth
feature draft has been scored on seven dimensions from 1 to 5. Write short
advice the writer can act on.

Write exactly these parts, in this order, each under its heading:

BIGGEST FIXES
Up to {MAX_FIXES} numbered fixes. Take the dimensions in FIX ORDER, from the top;
skip one only if no passage in the draft shows the problem. Each fix:
N. <Dimension> (<score>/5) — "<exact quote from the draft>" <what is wrong
with that passage, and exactly what to do instead>
If FIX ORDER is empty, write only this line: {ALL_FIVES_LINE}

WHAT'S WORKING
One strength, so the writer keeps it:
<Dimension> — "<exact quote from the draft>" <why it works>

LENGTH
Only when the draft is under {LENGTH_THRESHOLD} words: this exact line and nothing else.
{LENGTH_LINE}
When the draft is {LENGTH_THRESHOLD} words or more, leave out the LENGTH part.

Rules:
- Quotes are copied word for word from the draft, under {MAX_QUOTE_WORDS} words. Write any
  double quotation marks inside the passage as single quotes.
- Every fix points at a place in the draft. No generic tips ("show, don't
  tell", "add more quotes") without saying where and what.
- Don't mention length or word count outside the LENGTH part.
- Never give the chance of winning as a number or percentage.
- Don't recommend other stories or include links; they are added separately.
- Plain text only: no markdown, no bold."""


# ---------- loading ----------

def advice_dir(data_dir: str, *parts: str) -> str:
    return os.path.join(data_dir, "data", "advice", *parts)


def _fmt(score: float) -> str:
    """4.0 -> '4', 4.5 -> '4.5' (scores are averaged over runs)."""
    return str(int(score)) if score == int(score) else f"{score:g}"


def heldout_ids(data_dir: str) -> set[str]:
    """The 60 scorer-trial stories: never trained on."""
    path = os.path.join(trial_dir(data_dir), "stories.csv")
    return {r["id"] for r in _read_csv(path)} if os.path.exists(path) else set()


def load_stories(data_dir: str) -> dict[str, dict]:
    """Every scored feature, ready for ``build_prompt``: text with page
    leftovers removed (``prep.strip_layout``), averaged scores, run-1
    evidence quotes (only those still in that text) and the chance band.
    Word count is the cleaned text's; the band keeps Layer 3's."""
    text = {s["id"]: s for s in feature_set(data_dir)}
    evidence = load_scores(scores_file(data_dir, SCORER_MODEL))
    with open(os.path.join(data_dir, "data", "layer4_model.json"), encoding="utf-8") as f:
        model = json.load(f)
    out = {}
    for r in _read_csv(os.path.join(data_dir, "data", "layer3_scores.csv")):
        s = text.get(r["id"])
        if s is None:
            continue
        body = strip_layout(s["body"])
        scores = {k: float(r[k]) for k in DIMENSION_KEYS}
        ev = evidence.get(r["id"], {}).get("scores", {})
        quotes = {k: ev[k]["evidence"] if k in ev and evidence_found(ev[k]["evidence"], body) else ""
                  for k in DIMENSION_KEYS}
        row = dict(scores, log_words=math.log(max(int(r["word_count"]), 1)))
        out[r["id"]] = {"id": r["id"], "label": r["label"], "source": r["source"],
                        "school": r["school"], "title": s["title"], "body": body,
                        "word_count": word_count(body), "story_type": r["story_type"],
                        "scores": scores, "evidence": quotes,
                        "band": chance_band(predict(model, row)), "coefs": model["coefs"]}
    return out


# ---------- the pinned prompt ----------

def fix_order(scores: dict[str, float], coefs: dict[str, float]) -> list[str]:
    """Dimensions below 5, most important first.

    Priority is the gap to 5, nudged by the Layer 4 weight: x0.75 for a
    weight at or below zero up to x1.25 for the largest. Weight times gap
    (the first design) would never flag sourcing or depth, whose weights are
    about zero, even at 1/5; a x0.5-x1.5 nudge still put craft first for 632
    of 733 stories. Layer 4 is too unsure inside one school to overrule a
    big gap."""
    top = max((max(coefs.get(k, 0), 0) for k in DIMENSION_KEYS), default=0) or 1
    def priority(k):
        return (5 - scores[k]) * (WEIGHT_NUDGE[0] + (WEIGHT_NUDGE[1] - WEIGHT_NUDGE[0])
                                  * max(coefs.get(k, 0), 0) / top)
    below = [k for k in DIMENSION_KEYS if scores[k] < 5]
    return sorted(below, key=lambda k: (-priority(k), scores[k], DIMENSION_KEYS.index(k)))


def inputs_text(story: dict) -> str:
    wc = story["word_count"]
    order = fix_order(story["scores"], story["coefs"])
    lines = [f"TITLE: {story['title']}",
             f"WORD COUNT: {wc} ({'under' if wc < LENGTH_THRESHOLD else 'at least'} {LENGTH_THRESHOLD})",
             f"CHANCE BAND: {story['band']}",
             "SCORES (score, then the scorer's evidence quote):"]
    for k in DIMENSION_KEYS:
        ev = story["evidence"].get(k)
        lines.append(f"- {LABELS[k]}: {_fmt(story['scores'][k])}/5"
                     + (f' — "{ev}"' if ev else " — (no quote)"))
    lines.append("FIX ORDER: " + (", ".join(LABELS[k] for k in order) if order else "(empty)"))
    lines += ["", "DRAFT:", story["body"]]
    return "\n".join(lines)


def build_prompt(story: dict) -> str:
    """Instructions plus this draft's inputs, word for word the same in
    training and in use."""
    return f"{INSTRUCTIONS}\n\n{inputs_text(story)}"


# ---------- parsing and code checks ----------

HEADINGS = ("BIGGEST FIXES", "WHAT'S WORKING", "LENGTH")
_FIX = re.compile(r'^(\d+)\.\s+(.+?)\s+\((\d(?:\.\d+)?)/5\)\s+[—–-]+\s+"([^"]+)"\s*(.*)$', re.S)
_WORKING = re.compile(r'^(.+?)(?:\s+\(\d(?:\.\d+)?/5\))?\s+[—–-]+\s+"([^"]+)"\s*(.*)$', re.S)


def _sections(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Lines under each heading, and any problems with the headings."""
    found: dict[str, list[str]] = {}
    current, problems, order = None, [], []
    for line in text.replace("\r\n", "\n").split("\n"):
        head = line.strip().rstrip(":").upper().replace("’", "'")
        if head in HEADINGS:
            if head in found:
                problems.append(f"heading {head} appears twice")
            current = head
            found[head] = []
            order.append(head)
        elif current is None:
            if line.strip():
                problems.append("text before the first heading")
        else:
            found[current].append(line)
    if order != [h for h in HEADINGS if h in order]:
        problems.append("parts are out of order")
    return found, problems


def _paragraphs(lines: list[str], starts) -> list[str]:
    out: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if starts(line) or not out:
            out.append(line.strip())
        else:
            out[-1] += " " + line.strip()
    return out


def parse_advice(text: str) -> dict:
    """Split model advice into fixes, the strength and the length line."""
    found, problems = _sections(text)
    fixes = []
    for para in _paragraphs(found.get("BIGGEST FIXES", []), lambda l: re.match(r"^\s*\d+\.\s", l)):
        m = _FIX.match(para)
        if para == ALL_FIVES_LINE:
            continue
        if not m:
            problems.append(f"fix not in the format: {para[:60]!r}")
            continue
        fixes.append({"n": int(m[1]), "dim": _NAMES.get(m[2].strip().lower()), "name": m[2].strip(),
                      "score": m[3], "quote": m[4].strip(), "advice": m[5].strip()})
    working = None
    paras = _paragraphs(found.get("WHAT'S WORKING", []), lambda l: False)
    if paras:
        m = _WORKING.match(paras[0])
        if m:
            working = {"dim": _NAMES.get(m[1].strip().lower()), "name": m[1].strip(),
                       "quote": m[2].strip(), "advice": m[3].strip()}
        else:
            problems.append(f"strength not in the format: {paras[0][:60]!r}")
    length = "\n".join(l.strip() for l in found.get("LENGTH", []) if l.strip()) if "LENGTH" in found else None
    return {"fixes": fixes, "working": working, "length": length, "sections": found,
            "all_fives": ALL_FIVES_LINE in "\n".join(found.get("BIGGEST FIXES", [])),
            "problems": problems}


_BANNED = [
    (re.compile(r"\d+(?:\.\d+)?\s*%|\bpercent\b", re.I), "gives a percentage"),
    (re.compile(r"https?://|www\.|bestofsno\.com", re.I), "contains a link"),
    (re.compile(r"\*\*|^#+\s", re.M), "uses markdown"),
    (re.compile(r"\bword count\b|\b\d[\d,]*\s+words\b", re.I), "talks about length outside LENGTH"),
    (re.compile(r"STORIES TO LEARN FROM", re.I), "writes the stories part (code adds it)"),
    # Drafts reach the model with page leftovers stripped (prep.strip_layout);
    # a student's own draft has none, so advice about them is learned noise.
    (re.compile(r"pull[- ]quotes?|\bcaptions?\b|photo credits?|credit lines?|your browser|video tag"
                r"|audio clip|page (?:layout|clutter)|(?:web|page) (?:leftovers?|text|artifacts?)"
                r"|pasted (?:in|into)\b", re.I), "comments on page layout"),
]


def check_advice(text: str, story: dict) -> list[str]:
    """Code checks from the design; an empty list means the advice passes."""
    p = parse_advice(text)
    problems = list(p["problems"])
    order = fix_order(story["scores"], story["coefs"])
    body = story["body"]

    def quote_ok(q: str, where: str):
        if len(q.split()) >= MAX_QUOTE_WORDS:
            problems.append(f"{where}: quote is {len(q.split())} words (limit {MAX_QUOTE_WORDS})")
        if not evidence_found(q, body):
            problems.append(f"{where}: quote not in the draft: {q[:50]!r}")

    if "BIGGEST FIXES" not in p["sections"]:
        problems.append("missing BIGGEST FIXES")
    elif not order:
        if p["fixes"] or not p["all_fives"]:
            problems.append(f"every score is 5, so BIGGEST FIXES should be: {ALL_FIVES_LINE}")
    elif not p["fixes"]:
        problems.append("no fixes, but some dimensions are below 5")
    if len(p["fixes"]) > MAX_FIXES:
        problems.append(f"{len(p['fixes'])} fixes (limit {MAX_FIXES})")
    seen = []
    for i, fx in enumerate(p["fixes"], start=1):
        where = f"fix {i}"
        if fx["n"] != i:
            problems.append(f"{where}: numbered {fx['n']}")
        if fx["dim"] is None:
            problems.append(f"{where}: unknown dimension {fx['name']!r}")
            continue
        if fx["dim"] not in order:
            problems.append(f"{where}: {LABELS[fx['dim']]} scored 5 or isn't in FIX ORDER")
        elif fx["score"] != _fmt(story["scores"][fx["dim"]]):
            problems.append(f"{where}: score {fx['score']} but {LABELS[fx['dim']]} is "
                            f"{_fmt(story['scores'][fx['dim']])}")
        if fx["dim"] in seen:
            problems.append(f"{where}: {LABELS[fx['dim']]} fixed twice")
        seen.append(fx["dim"])
        if not fx["advice"]:
            problems.append(f"{where}: no advice after the quote")
        quote_ok(fx["quote"], where)
    ranked = [d for d in seen if d in order]
    if ranked != sorted(ranked, key=order.index):
        problems.append("fixes don't follow FIX ORDER")
    w = p["working"]
    if w is None:
        if not any("strength not in the format" in x for x in problems):
            problems.append("missing WHAT'S WORKING")
    else:
        if w["dim"] is None:
            problems.append(f"strength: unknown dimension {w['name']!r}")
        quote_ok(w["quote"], "strength")
    if story["word_count"] < LENGTH_THRESHOLD:
        if p["length"] != LENGTH_LINE:
            problems.append(f"under {LENGTH_THRESHOLD} words, so LENGTH must be exactly: {LENGTH_LINE}")
    elif p["length"] is not None:
        problems.append(f"LENGTH part on a draft of {LENGTH_THRESHOLD}+ words")
    model_part = "\n".join(p["sections"].get("BIGGEST FIXES", []) + p["sections"].get("WHAT'S WORKING", []))
    # Quotes are checked against the draft above; a draft's own "50% off" or
    # "1,200 words" isn't the model talking about chance or length.
    # Links stay banned even inside quotes.
    unquote = lambda t: re.sub(r'"[^"]*"', '""', t)
    for pattern, why in _BANNED:
        target = (unquote(model_part) if why.startswith("talks about length")
                  else unquote(text) if why == "gives a percentage" else text)
        if pattern.search(target):
            problems.append(why)
    return problems


# ---------- round 0: examples written by Claude subagents ----------

def _usable(s: dict) -> bool:
    return s["word_count"] >= MIN_WORDS and s.get("story_type", "feature") in ADVICE_TYPES


def pick_round0(stories: dict[str, dict], held: set[str], n: int = ROUND0_N,
                seed: int = SEED) -> list[str]:
    """Half non-winners, half winners; of the winners, up to half from the
    school sites (the rest archive), so school writing isn't drowned out."""
    rng = random.Random(seed)
    pool = [s for i, s in sorted(stories.items()) if i not in held and _usable(s)]
    non = [s["id"] for s in pool if s["label"] != "winner"]
    school = [s["id"] for s in pool if s["label"] == "winner" and s["source"] == "training"]
    archive = [s["id"] for s in pool if s["label"] == "winner" and s["source"] == "archive"]
    n_non = min(len(non), n // 2)
    n_school = min(len(school), (n - n_non) // 2)
    n_arch = min(len(archive), n - n_non - n_school)
    ids = rng.sample(non, n_non) + rng.sample(school, n_school) + rng.sample(archive, n_arch)
    rng.shuffle(ids)
    return ids


BATCH_HEADER = """# Advice batch {k} of {total}

Write advice for each story below, following the INSTRUCTIONS exactly. Each
story's inputs (title, word count, chance band, scores, FIX ORDER, draft)
come after its "=== STORY" line. Judge each story on its own.

Write your answers to `out_{k}.jsonl` in this folder, one JSON object per
line: {{"id": "<the story id>", "advice": "<the advice text, with \\n for new lines>"}}

Code checks every answer: quotes must be in the draft word for word
(punctuation and case don't matter), scores must match the inputs, fixes
must follow FIX ORDER, and the LENGTH part must appear only for drafts under
{threshold} words.

# INSTRUCTIONS

{instructions}
"""


def export_examples(data_dir: str, *, n: int = ROUND0_N, round_name: str = "round0",
                    skip_rounds: tuple[str, ...] = ()) -> dict:
    """Write batches for subagents. Stories that already have passing
    advice in ``skip_rounds`` are left out, so a new round adds to them."""
    stories = load_stories(data_dir)
    held = heldout_ids(data_dir)
    done = {i for r in skip_rounds for i in load_scores(advice_dir(data_dir, r, "examples.jsonl"))}
    if round_name in skip_rounds:
        raise ValueError("a round can't skip itself")
    ids = pick_round0(stories, held | done, n)
    out = advice_dir(data_dir, round_name)
    os.makedirs(out, exist_ok=True)
    batches = [ids[i:i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
    for k, batch in enumerate(batches, start=1):
        parts = [BATCH_HEADER.format(k=k, total=len(batches), threshold=LENGTH_THRESHOLD,
                                     instructions=INSTRUCTIONS)]
        parts += [f"\n=== STORY id: {i}\n\n{inputs_text(stories[i])}\n" for i in batch]
        with open(os.path.join(out, f"batch_{k}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
    with open(os.path.join(out, "ids.json"), "w", encoding="utf-8") as f:
        json.dump(ids, f, indent=1)
    return {"stories": len(ids), "batches": len(batches), "folder": out,
            "non_winners": sum(stories[i]["label"] != "winner" for i in ids)}


def import_examples(data_dir: str, *, round_name: str = "round0") -> dict:
    """Check every ``out_*.jsonl`` answer; passing ones go to
    ``examples.jsonl``, failing ones to ``rejected.jsonl`` with reasons."""
    folder = advice_dir(data_dir, round_name)
    with open(os.path.join(folder, "ids.json"), encoding="utf-8") as f:
        wanted = set(json.load(f))
    stories = load_stories(data_dir)
    passed, rejected, problems = {}, [], []
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("out_") and name.endswith(".jsonl")):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    sid, text = item["id"], item["advice"]
                except (ValueError, KeyError, TypeError) as e:
                    problems.append(f"{name}:{n}: {e}")
                    continue
                if sid not in wanted:
                    problems.append(f"{name}:{n}: id not in this round: {sid!r}")
                    continue
                found = (check_advice(text, stories[sid]) if _usable(stories[sid])
                         else [f"not in the advice pool ({stories[sid]['story_type']})"])
                if found:
                    rejected.append({"id": sid, "advice": text, "problems": found})
                else:
                    passed[sid] = {"id": sid, "advice": text.strip()}
    for fname, recs in (("examples.jsonl", list(passed.values())), ("rejected.jsonl", rejected)):
        with open(os.path.join(folder, fname), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in recs)
    reasons: dict[str, int] = {}
    for r in rejected:
        for pr in r["problems"]:
            key = pr.split(":")[0] if pr.startswith(("fix ", "strength")) else pr
            key = re.sub(r"fix \d+", "fix", key)
            reasons[key] = reasons.get(key, 0) + 1
    return {"passed": len(passed), "rejected": len(rejected),
            "missing": len(wanted - set(passed) - {r["id"] for r in rejected}),
            "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "file_problems": problems}


def export_train(data_dir: str, *, rounds: tuple[str, ...] = ("round0",)) -> dict:
    """Chat-format JSONL for the Colab notebook: one user turn (the pinned
    prompt) and one assistant turn (the advice). Later rounds override
    earlier ones for the same story. Held-out stories are refused."""
    stories = load_stories(data_dir)
    held = heldout_ids(data_dir)
    advice: dict[str, str] = {}
    for rnd in rounds:
        for rec in load_scores(advice_dir(data_dir, rnd, "examples.jsonl")).values():
            advice[rec["id"]] = rec["advice"]
    leaked = sorted(set(advice) & held)
    if leaked:
        raise ValueError(f"{len(leaked)} held-out stories in the training examples")
    path = advice_dir(data_dir, "train.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for sid, text in advice.items():
            msgs = [{"role": "user", "content": build_prompt(stories[sid])},
                    {"role": "assistant", "content": text}]
            f.write(json.dumps({"id": sid, "messages": msgs}) + "\n")
    return {"examples": len(advice), "path": path, "mb": round(os.path.getsize(path) / 1e6, 2)}


# ---------- stories to learn from ----------

def embed_text(title: str, body: str) -> str:
    return title + "\n\n" + " ".join(body.split()[:EMBED_WORDS])


def ollama_embed(texts: list[str], model: str = EMBED_MODEL, post=requests.post) -> list[list[float]]:
    resp = post(OLLAMA_EMBED_URL, json={"model": model, "input": texts}, timeout=600)
    resp.raise_for_status()
    vecs = resp.json()["embeddings"]
    if len(vecs) != len(texts):
        raise ValueError(f"asked for {len(texts)} embeddings, got {len(vecs)}")
    return vecs


def embeddings_path(data_dir: str, model: str = EMBED_MODEL) -> str:
    return advice_dir(data_dir, f"embeddings_{model.replace(':', '_').replace('/', '_')}.jsonl")


def pool_ids(stories: dict[str, dict], held: set[str]) -> list[str]:
    """Archive winners only: they're published on bestofsno.com, so each
    pick is a link anyone can open."""
    return [i for i, s in stories.items()
            if s["source"] == "archive" and i not in held and _usable(s)]


def embed(data_dir: str, *, model: str = EMBED_MODEL, embedder=ollama_embed, log=print) -> dict:
    """Cache an embedding for every scored feature (the pool plus the
    rest, so ``inspire ID`` works on any of them). Resumable."""
    stories = load_stories(data_dir)
    path = embeddings_path(data_dir, model)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    done = set(load_scores(path))
    todo = [i for i in stories if i not in done]
    with open(path, "a", encoding="utf-8") as f:
        for k in range(0, len(todo), EMBED_BATCH):
            chunk = todo[k:k + EMBED_BATCH]
            vecs = embedder([embed_text(stories[i]["title"], stories[i]["body"]) for i in chunk], model)
            for i, v in zip(chunk, vecs):
                f.write(json.dumps({"id": i, "model": model, "vector": v}) + "\n")
            f.flush()
            log(f"embedded {min(k + EMBED_BATCH, len(todo))}/{len(todo)}")
    return {"embedded": len(todo), "cached": len(done), "path": path}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def pick_inspiration(draft_vec: list[float], order: list[str], pool: list[dict]) -> list[tuple[dict, str]]:
    """``(winner, dimension)`` pairs, 2-3 of them.

    For each of the draft's top fixes, the most similar winner that scored
    5 on that dimension; failing that, the best scorer on it among the
    ``FALLBACK_POOL`` most similar. If fewer than two come out, the next
    most similar winners are added for their strongest dimension."""
    ranked = sorted(pool, key=lambda p: -_cosine(draft_vec, p["vector"]))
    picks: list[tuple[dict, str]] = []
    used: set[str] = set()
    for dim in order[:MAX_PICKS]:
        free = [p for p in ranked if p["id"] not in used]
        if not free:
            break
        best = next((p for p in free if p["scores"][dim] >= 5), None)
        if best is None:
            near = free[:FALLBACK_POOL]
            best = max(near, key=lambda p: (p["scores"][dim], -near.index(p)))
        picks.append((best, dim))
        used.add(best["id"])
    for p in ranked:
        if len(picks) >= MIN_PICKS:
            break
        if p["id"] not in used:
            dim = max(DIMENSION_KEYS, key=lambda k: (p["scores"][k], -DIMENSION_KEYS.index(k)))
            picks.append((p, dim))
            used.add(p["id"])
    return picks


def _month_year(published: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})", published or "")
    if not m:
        return ""
    months = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]
    return f"{months[int(m[2]) - 1]} {m[1]}"


def read_for(dim: str, score: float) -> str:
    """Filled from the winner's score and the rubric's words for it; no
    quoting the winner."""
    anchor = ANCHORS[dim][max(1, min(5, round(score))) - 1]
    return f"Read for {LABELS[dim].lower()} ({_fmt(score)}/5): {anchor}"


def render_inspiration(picks: list[tuple[dict, str]]) -> str:
    lines = ["STORIES TO LEARN FROM"]
    for p, dim in picks:
        meta = " — ".join(x for x in (p.get("school", ""), _month_year(p.get("published", ""))) if x)
        lines.append(f"• \"{p['title']}\"" + (f" — {meta}" if meta else "") + f" — {p['url']}")
        lines.append(f"  {read_for(dim, p['scores'][dim])}")
    return "\n".join(lines)


def load_pool(data_dir: str, stories: dict[str, dict], *, exclude: str | None = None,
              model: str = EMBED_MODEL) -> list[dict]:
    vecs = {i: r["vector"] for i, r in load_scores(embeddings_path(data_dir, model)).items()}
    meta = {r["id"]: r for r in _read_csv(os.path.join(data_dir, "data", "archive.csv"))}
    out = []
    for i in pool_ids(stories, heldout_ids(data_dir)):
        if i == exclude or i not in vecs or i not in meta:
            continue
        m = meta[i]
        out.append({"id": i, "vector": vecs[i], "scores": stories[i]["scores"], "title": m["title"],
                    "school": m["school"], "published": m["published"], "url": m["url"] or i})
    return out


def inspire(data_dir: str, story: dict, *, stories: dict[str, dict] | None = None,
            model: str = EMBED_MODEL, embedder=ollama_embed) -> str:
    """The "Stories to learn from" part for one draft (scored, with its
    ``fix_order`` known). Uses the cached vector if the draft is a stored
    story, so a story never recommends itself."""
    stories = stories if stories is not None else load_stories(data_dir)
    cached = load_scores(embeddings_path(data_dir, model)).get(story.get("id", ""))
    vec = cached["vector"] if cached else embedder([embed_text(story["title"], story["body"])], model)[0]
    pool = load_pool(data_dir, stories, exclude=story.get("id"), model=model)
    if not pool:
        raise ValueError("no embedded winners; run `python -m best_of_sno.advice embed` first")
    picks = pick_inspiration(vec, fix_order(story["scores"], story["coefs"]), pool)
    return render_inspiration(picks)


def full_advice(model_text: str, inspiration: str) -> str:
    return model_text.rstrip() + "\n\n" + inspiration


# ---------- command line ----------

def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").add_argument("id")
    ex = sub.add_parser("export-examples")
    ex.add_argument("--n", type=int, default=ROUND0_N)
    ex.add_argument("--round", default="round0")
    ex.add_argument("--skip-rounds", nargs="*", default=[],
                    help="leave out stories with passing advice in these rounds")
    sub.add_parser("import").add_argument("--round", default="round0")
    sub.add_parser("export-train").add_argument("--rounds", nargs="+", default=["round0"])
    sub.add_parser("check-train")
    sub.add_parser("embed").add_argument("--model", default=EMBED_MODEL)
    ins = sub.add_parser("inspire")
    ins.add_argument("id")
    ins.add_argument("--model", default=EMBED_MODEL)
    a = p.parse_args(argv)
    if a.cmd == "show":
        print(build_prompt(load_stories(a.data_dir)[a.id]))
    elif a.cmd == "export-examples":
        print(export_examples(a.data_dir, n=a.n, round_name=a.round, skip_rounds=tuple(a.skip_rounds)))
    elif a.cmd == "import":
        print(json.dumps(import_examples(a.data_dir, round_name=a.round), indent=1))
    elif a.cmd == "export-train":
        print(export_train(a.data_dir, rounds=tuple(a.rounds)))
    elif a.cmd == "check-train":
        from .advice_train import check_file
        print(check_file(advice_dir(a.data_dir, "train.jsonl"), heldout_ids(a.data_dir)))
    elif a.cmd == "embed":
        print(embed(a.data_dir, model=a.model))
    else:
        stories = load_stories(a.data_dir)
        print(inspire(a.data_dir, stories[a.id], stories=stories, model=a.model))


if __name__ == "__main__":
    main()
