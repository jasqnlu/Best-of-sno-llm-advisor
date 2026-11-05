"""Training helpers for the advice model, used by notebooks/qdora_advice.ipynb.

Plain functions with no torch import at the top, so they are tested offline
with a fake tokenizer. The notebook clones this repo on Colab and imports
them, so the masking it trains with is the masking tested here.

How an example is built (Gemma 4 chat format, thinking off):

    prompt = the chat template's generation prompt for the one user turn
             ("<bos><|turn>user\\n...<turn|>\\n<|turn>model\\n<|channel>thought\\n<channel|>")
    target = the advice + "<turn|>"

The prompt is exactly what Ollama sends at use time with thinking off, so
training and use match. Loss is on the target tokens only.
"""

from __future__ import annotations

import json
import random

END_OF_TURN = "<turn|>"
IGNORE = -100
MAX_LEN = 8192          # the scorer's num_ctx; the longest example is ~7.5k tokens
VAL_FRACTION = 0.05
SEED = 20261104


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def split(records: list[dict], val_fraction: float = VAL_FRACTION, seed: int = SEED
          ) -> tuple[list[dict], list[dict]]:
    """Seeded split by story id, so the same stories are always held back."""
    ids = sorted(r["id"] for r in records)
    rng = random.Random(seed)
    rng.shuffle(ids)
    n_val = max(1, round(len(ids) * val_fraction)) if len(ids) > 1 else 0
    val_ids = set(ids[:n_val])
    return ([r for r in records if r["id"] not in val_ids],
            [r for r in records if r["id"] in val_ids])


def render_prompt(tokenizer, user_text: str) -> str:
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": user_text}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False)


def build_example(tokenizer, record: dict, max_len: int = MAX_LEN) -> dict | None:
    """Token ids and labels for one ``{"messages": [user, assistant]}``
    record; ``None`` if it doesn't fit in ``max_len`` (never cut: a cut
    draft or cut advice would teach the wrong thing)."""
    msgs = record["messages"]
    if [m["role"] for m in msgs] != ["user", "assistant"]:
        raise ValueError(f"{record.get('id')}: expected one user and one assistant turn")
    prompt_ids = tokenizer(render_prompt(tokenizer, msgs[0]["content"]),
                           add_special_tokens=False)["input_ids"]
    target_ids = tokenizer(msgs[1]["content"].strip() + END_OF_TURN,
                           add_special_tokens=False)["input_ids"]
    ids = prompt_ids + target_ids
    if len(ids) > max_len:
        return None
    return {"input_ids": ids, "attention_mask": [1] * len(ids),
            "labels": [IGNORE] * len(prompt_ids) + target_ids}


def build_all(tokenizer, records: list[dict], max_len: int = MAX_LEN) -> tuple[list[dict], list[str]]:
    """Examples that fit, and the ids of those that didn't."""
    out, too_long = [], []
    for r in records:
        ex = build_example(tokenizer, r, max_len)
        if ex is None:
            too_long.append(r["id"])
        else:
            out.append(ex)
    return out, too_long


def pad_batch(batch: list[dict], pad_id: int) -> dict[str, list[list[int]]]:
    """Right-pad to the longest example; padding is masked out of the loss."""
    width = max(len(b["input_ids"]) for b in batch)
    def pad(seq, value):
        return seq + [value] * (width - len(seq))
    return {"input_ids": [pad(b["input_ids"], pad_id) for b in batch],
            "attention_mask": [pad(b["attention_mask"], 0) for b in batch],
            "labels": [pad(b["labels"], IGNORE) for b in batch]}


def estimate_tokens(text: str) -> int:
    """Rough count for checking files offline: the scorer's real counts ran
    about 1.35 tokens per word on these stories."""
    return int(len(text.split()) * 1.35) + 16


def check_file(path: str, held_ids: set[str], max_len: int = MAX_LEN) -> dict:
    """Offline checks before uploading train.jsonl: shape, no held-out
    story, and an estimate of how many would not fit."""
    recs = load_jsonl(path)
    problems = []
    for r in recs:
        roles = [m.get("role") for m in r.get("messages", [])]
        if roles != ["user", "assistant"]:
            problems.append(f"{r.get('id')}: roles {roles}")
    leaked = sorted({r["id"] for r in recs} & held_ids)
    est = [estimate_tokens(r["messages"][0]["content"]) + estimate_tokens(r["messages"][1]["content"])
           for r in recs if len(r.get("messages", [])) == 2]
    train, val = split(recs)
    return {"examples": len(recs), "train": len(train), "val": len(val),
            "held_out_leaked": leaked, "shape_problems": problems,
            "est_tokens_max": max(est, default=0),
            "est_tokens_median": sorted(est)[len(est) // 2] if est else 0,
            "est_over_max_len": sum(e > max_len for e in est)}
