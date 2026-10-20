"""Embedder A/B — score one embedder over a probe set, then compare runs.

Measures the configured embedder (whatever `brain.embed` is on PYTHONPATH, with
its env) against a corpus DB, two ways per probe:

  - hybrid:   store.recall — what consumers actually get (semantic + lexical RRF)
  - semantic: the cosine arm alone — isolates the embedder, since the lexical arm
              masks embedder differences on keyword-heavy queries

Source-granularity scoring (did a relevant source's chunk reach the top-k), like
recall_scorecard.py. Read-only against --dsn; point it at a COPY re-embedded with
`python -m brain.reembed` (see README.md, "Embedder A/B").

Usage:
    python embedder_ab.py --dsn postgresql://... --probes probes_embedder.json \
        --label embeddinggemma > embeddinggemma.json
    python embedder_ab.py --compare voyage-3-lite.json embeddinggemma.json nomic-embed-text.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import asyncpg
from pgvector.asyncpg import register_vector

from brain import store
from brain.embed import embed


def _score(retrieved: list[str], relevant: list[str], k: int) -> dict:
    rel = set(relevant)
    rr = next((1.0 / i for i, s in enumerate(retrieved, 1) if s in rel), 0.0)
    return {"hit": float(bool(rel & set(retrieved[:k]))), "rr": rr}


async def _semantic_sources(pool, q_emb) -> list[str]:
    rows = await pool.fetch(
        "SELECT c.source_id::text AS sid FROM chunks c "
        "ORDER BY c.embedding <=> $1 LIMIT 50",
        q_emb,
    )
    return list(dict.fromkeys(r["sid"] for r in rows))


async def run(dsn: str, probes: list[dict], k: int, label: str) -> dict:
    pool = await asyncpg.create_pool(dsn, init=register_vector)
    per = []
    try:
        for p in probes:
            t0 = time.perf_counter()
            [q_emb] = await asyncio.to_thread(embed, [p["query"]], "query")
            ms = (time.perf_counter() - t0) * 1000
            semantic = await _semantic_sources(pool, q_emb)
            hybrid = list(dict.fromkeys(c.source_id for c in await store.recall(pool, p["query"], k=50)))
            per.append({
                "query": p["query"],
                "kind": p.get("kind", "legacy"),
                "embed_ms": round(ms, 1),
                "hybrid": _score(hybrid, p["relevant"], k),
                "semantic": _score(semantic, p["relevant"], k),
            })
    finally:
        await pool.close()
    return {"label": label, "k": k, "per_probe": per}


def _agg(per: list[dict], arm: str) -> tuple[float, float]:
    n = len(per) or 1
    return (sum(p[arm]["hit"] for p in per) / n, sum(p[arm]["rr"] for p in per) / n)


def compare(paths: list[str]) -> None:
    runs = [json.load(open(p)) for p in paths]
    kinds = sorted({p["kind"] for r in runs for p in r["per_probe"]})
    k = runs[0]["k"]
    print(f"{'embedder':<24}{'subset':<12}{'n':>4}  {'hybrid R@'+str(k):>10} {'MRR':>6}  {'semantic R@'+str(k):>12} {'MRR':>6}")
    for r in runs:
        for subset in ["all", *kinds]:
            per = [p for p in r["per_probe"] if subset == "all" or p["kind"] == subset]
            (hh, hm), (sh, sm) = _agg(per, "hybrid"), _agg(per, "semantic")
            print(f"{r['label']:<24}{subset:<12}{len(per):>4}  {hh:>10.3f} {hm:>6.3f}  {sh:>12.3f} {sm:>6.3f}")
        lat = sorted(p["embed_ms"] for p in r["per_probe"])
        print(f"{'':<24}query embed ms: p50={lat[len(lat) // 2]:.0f} p90={lat[int(len(lat) * 0.9)]:.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn")
    ap.add_argument("--probes")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--label", default="run")
    ap.add_argument("--compare", nargs="+")
    a = ap.parse_args()
    if a.compare:
        compare(a.compare)
        return
    probes = json.load(open(a.probes))
    print(json.dumps(asyncio.run(run(a.dsn, probes, a.k, a.label)), indent=1))


if __name__ == "__main__":
    main()
