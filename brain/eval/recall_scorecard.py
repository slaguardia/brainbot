"""Recall scorecard for the brain — the Phase 0/3 note-legibility eval harness.

Given a probe set (queries paired with their known-relevant source ids) and a
running brain's base URL, measure recall@k, precision@k, and MRR over `/recall`.
Run it twice — once with legibility OFF (the heading-only baseline), once with the
rewrite applied (treatment) — and diff the aggregates to read where a rewrite lifts
recall and at what health score. The trigger threshold (`legibility.threshold`) is
meant to be read off that curve, not guessed. See `docs/note-legibility.md`
(Eval / A/B plan).

Stdlib only (urllib + json) so it runs anywhere the brain is reachable — no deps,
no embedder. It's the recall@k / precision scorecard the `test-brain` skill calls
for; point it at the brain and a probe file.

Usage:
    python recall_scorecard.py --brain http://127.0.0.1:8100 --probes probes.json --k 5
    python recall_scorecard.py ... --label baseline > baseline.json
    python recall_scorecard.py ... --label treatment > treatment.json
    python recall_scorecard.py --compare baseline.json treatment.json   # diff two runs

Probe file (JSON list):
    [{"query": "how did you handle daily-patched container images",
      "relevant": ["37a7973a-5453-80d0-ae47-c980c71d5cf0"]}, ...]

Recall is measured at SOURCE granularity — did a chunk from a relevant source
appear in the top-k — because that's what a consumer escalates on (recall -> the
owning source id -> doc(id)). A larger, messier corpus is where the rewrite's
chunk-discrimination benefit shows; on a small or already-structured corpus the
deltas are near zero (a true headingless dump still has nothing to be confused
with). Read the numbers with the corpus size in mind.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request


def recall_sources(brain: str, query: str, k: int) -> list[str]:
    """The distinct source ids returned by /recall for `query`, in rank order."""
    qs = urllib.parse.urlencode({"q": query, "k": k})
    with urllib.request.urlopen(f"{brain}/recall?{qs}", timeout=30) as resp:
        body = json.load(resp)
    seen: list[str] = []
    for chunk in body.get("chunks", []):
        sid = chunk.get("id")
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def score_probe(retrieved: list[str], relevant: list[str], k: int) -> dict:
    """recall@k / precision@k / reciprocal-rank for one probe (source granularity)."""
    rel = set(relevant)
    topk = retrieved[:k]
    hits = [s for s in topk if s in rel]
    recall = len(set(hits)) / len(rel) if rel else 0.0
    precision = len(hits) / len(topk) if topk else 0.0
    rr = 0.0
    for i, sid in enumerate(retrieved, start=1):
        if sid in rel:
            rr = 1.0 / i
            break
    return {"recall": recall, "precision": precision, "rr": rr, "retrieved": topk}


def run(brain: str, probes: list[dict], k: int, label: str) -> dict:
    per = []
    for p in probes:
        retrieved = recall_sources(brain, p["query"], k)
        s = score_probe(retrieved, p.get("relevant", []), k)
        per.append({"query": p["query"], **s})
    n = len(per) or 1
    agg = {
        "recall@k": round(sum(x["recall"] for x in per) / n, 4),
        "precision@k": round(sum(x["precision"] for x in per) / n, 4),
        "mrr": round(sum(x["rr"] for x in per) / n, 4),
    }
    return {"label": label, "k": k, "n": len(per), "aggregate": agg, "probes": per}


def _print_run(result: dict) -> None:
    print(f"# {result['label']}  (k={result['k']}, n={result['n']})", file=sys.stderr)
    a = result["aggregate"]
    print(
        f"  recall@k={a['recall@k']}  precision@k={a['precision@k']}  mrr={a['mrr']}",
        file=sys.stderr,
    )
    for p in result["probes"]:
        flag = "ok " if p["recall"] >= 0.999 else "MISS"
        print(f"  [{flag}] r={p['recall']:.2f} mrr={p['rr']:.2f}  {p['query'][:60]}", file=sys.stderr)


def _compare(base_path: str, treat_path: str) -> None:
    base = json.load(open(base_path))
    treat = json.load(open(treat_path))
    print(f"# baseline vs treatment (k={base['k']})")
    for key in ("recall@k", "precision@k", "mrr"):
        b, t = base["aggregate"][key], treat["aggregate"][key]
        print(f"  {key:12} {b:.4f} -> {t:.4f}  (Δ {t - b:+.4f})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brain", default="http://127.0.0.1:8100")
    ap.add_argument("--probes")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--label", default="run")
    ap.add_argument("--compare", nargs=2, metavar=("BASELINE", "TREATMENT"))
    args = ap.parse_args()

    if args.compare:
        _compare(*args.compare)
        return
    if not args.probes:
        ap.error("--probes is required (or use --compare)")
    probes = json.load(open(args.probes))
    result = run(args.brain, probes, args.k, args.label)
    _print_run(result)  # human-readable to stderr
    print(json.dumps(result, indent=2))  # machine-readable to stdout (redirect to a file)


if __name__ == "__main__":
    main()
