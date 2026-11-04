"""Draw the README charts as SVG from the local data files.

Run from the repo root:  python docs/images/make_charts.py

Reads best_of_sno/data/{training,archive}.csv and writes only aggregate counts
into the SVGs (never story text). The Layer 3 chart uses the results table in
docs/superpowers/specs/2026-11-01-layer3-subscore-rubric-design.md, because the
score file lives on the machine that ran the scorer. Uses no plotting library, so the project
needs no extra dependency. Each SVG carries its own light/dark colors.
"""

import collections
import csv
import statistics
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "best_of_sno" / "data"
OUT = Path(__file__).resolve().parent

csv.field_size_limit(2**31 - 1)  # sys.maxsize overflows on Windows

SCHOOLS = [
    ("scotscoop.com", "Carlmont"),
    ("harkeraquila.com", "Harker"),
    ("torreypinesfalconer.com", "Torrey Pines"),
    ("theburlingameb.org", "Burlingame"),
]

STYLE = """
<style>
  svg { --bg:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --grid:#e4e3df;
        --s1:#2a78d6; --s2:#eb6834; --s3:#6250d6; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
  @media (prefers-color-scheme: dark) {
    svg { --bg:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --grid:#3a3a37;
          --s1:#3987e5; --s2:#d95926; --s3:#9085e9; }
  }
  .bg { fill:var(--bg); }
  .t  { fill:var(--ink); font-size:16px; font-weight:600; }
  .st { fill:var(--ink2); font-size:12px; }
  .l  { fill:var(--ink2); font-size:12px; }
  .v  { fill:var(--ink); font-size:12px; font-variant-numeric:tabular-nums; }
  .g  { stroke:var(--grid); stroke-width:1; }
  .s1 { fill:var(--s1); } .s2 { fill:var(--s2); } .s3 { fill:var(--s3); }
  .m  { stroke:var(--ink2); stroke-width:1.5; stroke-dasharray:4 3; }
</style>
"""


def read(name):
    with open(DATA / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def bar(x, y, w, h, cls, horizontal=False):
    """A bar with 4px rounded data-end and a square baseline end."""
    if w <= 0 or h <= 0:
        return ""
    r = min(4, w if horizontal else h, h if horizontal else w / 2)
    if horizontal:  # baseline on the left, round the right end
        return (f'<path class="{cls}" d="M{x},{y} h{w - r} q{r},0 {r},{r} '
                f'v{h - 2 * r} q0,{r} -{r},{r} h-{w - r} z"/>')
    return (f'<path class="{cls}" d="M{x},{y + h} v-{h - r} q0,-{r} {r},-{r} '
            f'h{w - 2 * r} q{r},0 {r},{r} v{h - r} z"/>')


def svg(w, h, title, subtitle, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
            f"<title>{escape(title)}</title>{STYLE}"
            f'<rect class="bg" width="{w}" height="{h}" rx="10"/>'
            f'<text class="t" x="24" y="34">{escape(title)}</text>'
            f'<text class="st" x="24" y="54">{escape(subtitle)}</text>'
            f"{body}</svg>\n")


def legend(x, y, items):
    out, cx = [], x
    for cls, label in items:
        out.append(f'<rect class="{cls}" x="{cx}" y="{y - 9}" width="10" height="10" rx="2"/>'
                   f'<text class="l" x="{cx + 15}" y="{y}">{escape(label)}</text>')
        cx += 30 + 7 * len(label)
    return "".join(out)


def chart_schools(rows):
    """Winners and non-winners per school, plus the win rate."""
    counts = collections.Counter((r["source_site"], r["label"]) for r in rows)
    W, H, left, top, rowh = 720, 300, 130, 96, 46
    maxv = max(counts.values())
    plot = 440
    body = [legend(24, 80, [("s1", "Winners"), ("s2", "Non-winners")])]
    for i, (host, name) in enumerate(SCHOOLS):
        y = top + i * rowh
        w, n = counts[(host, "winner")], counts[(host, "non_winner")]
        body.append(f'<text class="l" x="{left - 12}" y="{y + 18}" text-anchor="end">{name}</text>')
        for j, (v, cls) in enumerate(((w, "s1"), (n, "s2"))):
            bw = max(2, plot * v / maxv)
            by = y + j * 16
            body.append(bar(left, by, bw, 14, cls, horizontal=True))
            body.append(f'<text class="v" x="{left + bw + 6}" y="{by + 11}">{v:,}</text>')
        rate = 100 * w / (w + n)
        body.append(f'<text class="st" x="{W - 24}" y="{y + 18}" text-anchor="end">{rate:.1f}% won</text>')
    body.append(f'<line class="g" x1="{left}" x2="{left}" y1="{top - 6}" y2="{top + 4 * rowh - 10}"/>')
    tw, tn = sum(counts[(h, "winner")] for h, _ in SCHOOLS), sum(counts[(h, "non_winner")] for h, _ in SCHOOLS)
    return svg(W, H, "Training set by school",
               f"{tw} winners vs {tn:,} non-winners, published Dec 2025 – Sep 2026 "
               f"(training.csv)", "".join(body))


def chart_words(rows):
    """Share of each class per word-count bin, with medians."""
    edges = [0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2500, 3000]
    labels = ["<250", "250", "500", "750", "1k", "1.25k", "1.5k", "1.75k", "2k", "2.5k", "3k+"]
    groups = {}
    for lab in ("winner", "non_winner"):
        wc = [int(r["word_count"]) for r in rows if r["label"] == lab]
        hist = [0] * len(edges)
        for v in wc:
            hist[max(i for i, e in enumerate(edges) if v >= e)] += 1
        groups[lab] = ([100 * h / len(wc) for h in hist], statistics.median(wc))
    W, H, left, top, plot_h = 720, 340, 56, 90, 190
    slot = (W - left - 24) / len(edges)
    maxp = max(max(p) for p, _ in groups.values())
    ceil = 35
    assert maxp <= ceil
    body = [legend(24, 76, [("s1", f"Winners (median {groups['winner'][1]:,.0f} words)"),
                            ("s2", f"Non-winners (median {groups['non_winner'][1]:,.0f} words)")])]
    for p in range(0, ceil + 1, 10):
        y = top + plot_h - plot_h * p / ceil
        body.append(f'<line class="g" x1="{left}" x2="{W - 24}" y1="{y}" y2="{y}"/>'
                    f'<text class="l" x="{left - 8}" y="{y + 4}" text-anchor="end">{p}%</text>')
    bw = (slot - 8) / 2
    for i in range(len(edges)):
        x = left + i * slot + 3
        for j, (lab, cls) in enumerate((("winner", "s1"), ("non_winner", "s2"))):
            v = groups[lab][0][i]
            h = plot_h * v / ceil
            body.append(bar(x + j * (bw + 2), top + plot_h - h, bw, h, cls))
        body.append(f'<text class="l" x="{x + slot / 2 - 3}" y="{top + plot_h + 18}" '
                    f'text-anchor="middle">{escape(labels[i])}</text>')
    body.append(f'<text class="st" x="{W / 2}" y="{H - 16}" text-anchor="middle">'
                f'Story length in words (bin start) · bars show % of each group</text>')
    return svg(W, H, "Winners run about twice as long",
               "Why the rubric must not reward length itself (training.csv)", "".join(body))


def split_cats(value):
    return [c.strip() for c in value.split(",") if c.strip()]


def chart_categories(rows):
    """Top site categories, as % of each class."""
    out = {}
    for lab in ("winner", "non_winner"):
        sub = [r for r in rows if r["label"] == lab]
        c = collections.Counter(c for r in sub for c in set(split_cats(r["categories"])))
        out[lab] = (c, len(sub))
    cats = ["Features", "News", "Sports", "Opinion", "Class of 2026", "Briefs", "A&E", "Editorial"]
    W, left, top, rowh = 720, 130, 96, 40
    H = top + rowh * len(cats) + 20
    plot = 470
    body = [legend(24, 80, [("s1", "Winners"), ("s2", "Non-winners")])]
    for i, cat in enumerate(cats):
        y = top + i * rowh
        body.append(f'<text class="l" x="{left - 12}" y="{y + 18}" text-anchor="end">{escape(cat)}</text>')
        for j, (lab, cls) in enumerate((("winner", "s1"), ("non_winner", "s2"))):
            c, n = out[lab]
            p = 100 * c[cat] / n
            bw = max(2, plot * p / 75)
            by = y + j * 15
            body.append(bar(left, by, bw, 13, cls, horizontal=True))
            body.append(f'<text class="v" x="{left + bw + 6}" y="{by + 11}">{p:.0f}%</text>')
    return svg(W, H, "Winners are mostly features",
               "Share of each group tagged with a site category (training.csv)", "".join(body))


def chart_archive(rows):
    """Best of SNO winners per month in the archive corpus."""
    months = collections.Counter(r["published"][:7] for r in rows if r["published"])
    keys = [f"{y}-{m:02d}" for y, m in [(2025, 12)] + [(2026, m) for m in range(1, 11)]]
    names = ["Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]
    W, H, left, top, plot_h = 720, 300, 56, 76, 170
    ceil = 350
    slot = (W - left - 24) / len(keys)
    body = []
    for v in range(0, ceil + 1, 100):
        y = top + plot_h - plot_h * v / ceil
        body.append(f'<line class="g" x1="{left}" x2="{W - 24}" y1="{y}" y2="{y}"/>'
                    f'<text class="l" x="{left - 8}" y="{y + 4}" text-anchor="end">{v}</text>')
    for i, k in enumerate(keys):
        v = months[k]
        h = plot_h * v / ceil
        x = left + i * slot + 8
        body.append(bar(x, top + plot_h - h, slot - 16, h, "s1"))
        if v:
            body.append(f'<text class="v" x="{x + (slot - 16) / 2}" y="{top + plot_h - h - 6}" '
                        f'text-anchor="middle">{v}</text>')
        body.append(f'<text class="l" x="{x + (slot - 16) / 2}" y="{top + plot_h + 18}" '
                    f'text-anchor="middle">{names[i]}</text>')
    gap_x = left + 6 * slot + 8
    body.append(f'<text class="st" x="{gap_x + 1.5 * slot - 8}" y="{top + plot_h - 20}" '
                f'text-anchor="middle">Jun – Aug: none (summer)</text>')
    total = sum(months[k] for k in keys)
    return svg(W, H, "The winners corpus",
               f"{total:,} Best of SNO winners by republish month, Dec 2025 – Oct 2026 (archive.csv)",
               "".join(body))


# AUC per Layer 3 score (Gemma 12B, 733 feature stories), from the design doc.
# (name, AUC school winners vs school non-winners, AUC with archive winners added)
LAYER3_AUC = [
    ("Total of 7", 0.81, 0.71),
    ("Significance", 0.83, 0.65),
    ("Depth", 0.81, 0.65),
    ("Sourcing", 0.70, 0.63),
    ("Quotes", 0.70, 0.65),
    ("Craft", 0.69, 0.67),
    ("Lede", 0.68, 0.65),
    ("Focus", 0.53, 0.59),
    ("Word count alone", 0.77, 0.62),
]


def chart_layer3():
    """How well each score separates winners, measured from a coin flip."""
    W, left, top, rowh = 720, 150, 100, 38
    H = top + rowh * len(LAYER3_AUC) + 44
    lo, hi = 0.5, 0.9
    plot = W - left - 70
    def x(v):
        return left + plot * (v - lo) / (hi - lo)
    body = [legend(24, 80, [("s1", "School winners vs non-winners"),
                            ("s3", "Adding 518 archive winners")])]
    for v in (0.5, 0.6, 0.7, 0.8, 0.9):
        body.append(f'<line class="g" x1="{x(v)}" x2="{x(v)}" y1="{top - 6}" y2="{H - 40}"/>'
                    f'<text class="l" x="{x(v)}" y="{H - 24}" text-anchor="middle">{v:.1f}</text>')
    for i, (name, a, b) in enumerate(LAYER3_AUC):
        y = top + i * rowh + (10 if name == "Word count alone" else 0)
        cls = "t" if name == "Total of 7" else "l"
        weight = ' style="font-size:12px"' if cls == "t" else ""
        body.append(f'<text class="{cls}" x="{left - 12}" y="{y + 16}" text-anchor="end"{weight}>'
                    f'{escape(name)}</text>')
        for j, (v, c) in enumerate(((a, "s1"), (b, "s3"))):
            by = y + j * 14
            body.append(bar(x(lo), by, max(2, x(v) - x(lo)), 12, c, horizontal=True))
            body.append(f'<text class="v" x="{x(v) + 6}" y="{by + 10}">{v:.2f}</text>')
    body.append(f'<text class="st" x="{x(0.7)}" y="{H - 8}" text-anchor="middle">'
                f'AUC: chance a winner outscores a non-winner · 0.5 = coin flip</text>')
    return svg(W, H, "Which scores pick out winners",
               "Gemma 12B scores on 733 in-depth features (Layer 3 design doc)", "".join(body))


def main():
    training, archive = read("training.csv"), read("archive.csv")
    charts = {
        "schools.svg": chart_schools(training),
        "word-counts.svg": chart_words(training),
        "categories.svg": chart_categories(training),
        "archive-months.svg": chart_archive(archive),
        "layer3-auc.svg": chart_layer3(),
    }
    for name, text in charts.items():
        (OUT / name).write_text(text, encoding="utf-8")
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
