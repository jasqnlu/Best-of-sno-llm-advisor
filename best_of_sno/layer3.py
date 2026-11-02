"""Layer 3: score every feature story with the chosen scorer.

    python -m best_of_sno.layer3 score gemma4:12b   # resumable; hours on 12B
    python -m best_of_sno.layer3 export gemma4:12b  # -> data/layer3_scores.csv

The stories are the chance-bar scope the owner chose: every feature in
training.csv (winners and non-winners) plus the archive's feature winners.
Archive winners that are already training winners (same story, Best of SNO
copy) are skipped, and so are the archive's short "view on the original
site" stubs, which aren't story text. Archive bodies get the same
``clean_body`` as training rows, so the scorer sees both sources alike.

Scores from the trial (same model, same pinned setup, same text) are
reused rather than run again.
"""

from __future__ import annotations

import argparse
import csv
import json
import os

from .layer3_trial import _is_feature, _read_csv, load_scores, scores_path
from .prep import clean_body
from .scorer import DIMENSION_KEYS, long_enough, score_with_ollama
from .scraper import word_count

# Archive features run 1,000+ words; the 53 under this are stubs of 35-55
# words and nothing sits between 60 and 300.
MIN_ARCHIVE_WORDS = 100
EXPORT_COLUMNS = (["id", "label", "source", "school", "word_count", "long_enough", "story_type"]
                  + DIMENSION_KEYS + ["total"])


def data_path(data_dir: str, name: str) -> str:
    return os.path.join(data_dir, "data", name)


def feature_set(data_dir: str) -> list[dict]:
    """Training features, then archive feature winners not already in."""
    training = _read_csv(data_path(data_dir, "training.csv"))
    out = [{"id": r["id"], "label": r["label"], "source": "training", "school": r["school"],
            "word_count": int(r["word_count"]), "title": r["title"], "body": r["body"]}
           for r in training if _is_feature(r)]
    already = {r["matched_id"] for r in training if r.get("matched_id")}
    for r in _read_csv(data_path(data_dir, "archive.csv")):
        if not _is_feature(r) or r["id"] in already:
            continue
        body = clean_body(r["body"])
        wc = word_count(body)
        if wc < MIN_ARCHIVE_WORDS:
            continue
        out.append({"id": r["id"], "label": "winner", "source": "archive", "school": r["school"],
                    "word_count": wc, "title": r["title"], "body": body})
    return out


def scores_file(data_dir: str, model: str) -> str:
    safe = model.replace(":", "_").replace("/", "_")
    return data_path(data_dir, f"layer3_scores_{safe}.jsonl")


def score(data_dir: str, model: str, *, scorer=score_with_ollama, log=print) -> dict:
    stories = feature_set(data_dir)
    path = scores_file(data_dir, model)
    done = {i for i, r in load_scores(path).items() if "scores" in r}
    trial = {i: r for i, r in load_scores(scores_path(data_dir, model)).items() if "scores" in r}
    counts = {"stories": len(stories), "scored": 0, "reused": 0, "errors": 0, "skipped": len(done)}
    with open(path, "a", encoding="utf-8") as f:
        for n, s in enumerate(stories, start=1):
            if s["id"] in done:
                continue
            if s["id"] in trial:
                rec, kind = dict(trial[s["id"]]), "reused"
            else:
                rec = {"id": s["id"], "model": model, **scorer(model, s["title"], s["body"])}
                kind = "errors" if "error" in rec else "scored"
                log(f"[{n}/{len(stories)}] {model} {rec.get('seconds')}s "
                    + (f"ERROR {rec['error']}" if "error" in rec else "ok"))
            f.write(json.dumps(rec) + "\n")
            f.flush()
            counts[kind] += 1
    return counts


def export(data_dir: str, model: str) -> dict:
    """One row per scored story for Layer 4. Word count is its own column,
    so Layer 4 learns how much length matters on top of the scores."""
    stories = feature_set(data_dir)
    recs = load_scores(scores_file(data_dir, model))
    rows, missing = [], 0
    for s in stories:
        r = recs.get(s["id"], {})
        if "scores" not in r:
            missing += 1
            continue
        sc = r["scores"]
        row = {k: s[k] for k in ("id", "label", "source", "school", "word_count")}
        row["long_enough"] = int(long_enough(s["word_count"]))
        row["story_type"] = sc["story_type"]
        row.update({k: sc[k]["score"] for k in DIMENSION_KEYS})
        row["total"] = sum(sc[k]["score"] for k in DIMENSION_KEYS)
        rows.append(row)
    path = data_path(data_dir, "layer3_scores.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return {"rows": len(rows), "missing": missing, "path": path}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)))
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("score", "export"):
        sub.add_parser(name).add_argument("model")
    a = p.parse_args(argv)
    print((score if a.cmd == "score" else export)(a.data_dir, a.model))


if __name__ == "__main__":
    main()
