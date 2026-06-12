"""note-legibility A/B driver — baseline (heading-only) vs treatment (rewrite).

Runs the whole experiment IN AN ISOLATED eval database, reading the real corpus's
raw_text from a source brain and never touching it:

  1. ingest the content sources into the eval DB with legibility OFF  -> baseline
  2. measure recall@k / MRR over the probe set (real Voyage embeddings)
  3. force-rewrite the named headingless dump(s) with legibility ON   -> treatment
     (real Anthropic call; only the named sources change, so the delta is isolated)
  4. measure the same probes again, and diff per-probe

In-process (uses store.recall directly — no HTTP service to stand up). Needs the
real VOYAGE_API_KEY + ANTHROPIC_API_KEY in env and the brain package importable.
Re-run it when the corpus grows into more messy dumps — that's when recall@k (not
just MRR on one buried sub-idea) gets the headroom to set `legibility.threshold`.

Usage:
    python run_ab.py \
        --source-dsn  postgresql://brain:PW@host:5432/brain \
        --eval-dsn    postgresql://brain:PW@host:5432/brain_eval \
        --probes      probes.json \
        --rewrite     37a7973a-5453-80d0-ae47-c980c71d5cf0   # repeatable
"""

from __future__ import annotations

import argparse
import asyncio
import json

import asyncpg
from pgvector.asyncpg import register_vector

from brain import store
from brain.db import apply_schema
from brain.settings import LEGIBILITY_ENABLED_KEY, LEGIBILITY_MODE_KEY, set_setting


def _score(retrieved: list[str], relevant: list[str], k: int) -> dict:
    rel = set(relevant)
    topk = retrieved[:k]
    hits = [s for s in topk if s in rel]
    rr = next((1.0 / i for i, s in enumerate(retrieved, 1) if s in rel), 0.0)
    return {
        "recall": len(set(hits)) / len(rel) if rel else 0.0,
        "precision": len(hits) / len(topk) if topk else 0.0,
        "rr": rr,
    }


async def _recall_sources(pool, query: str, k: int) -> list[str]:
    chunks = await store.recall(pool, query, k=k)
    out: list[str] = []
    for c in chunks:
        if c.source_id and c.source_id not in out:
            out.append(c.source_id)
    return out


async def _measure(pool, probes: list[dict], k: int) -> dict:
    per = []
    for p in probes:
        retrieved = await _recall_sources(pool, p["query"], k)
        per.append({"query": p["query"], **_score(retrieved, p.get("relevant", []), k)})
    n = len(per) or 1
    return {
        "recall@k": round(sum(x["recall"] for x in per) / n, 4),
        "precision@k": round(sum(x["precision"] for x in per) / n, 4),
        "mrr": round(sum(x["rr"] for x in per) / n, 4),
        "per": per,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dsn", required=True)
    ap.add_argument("--eval-dsn", required=True)
    ap.add_argument("--probes", required=True)
    ap.add_argument("--rewrite", action="append", default=[], help="source id to rewrite (repeatable)")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    probes = json.load(open(args.probes))
    rewrite_ids = set(args.rewrite)

    # Read the content sources (raw_text) from the live brain — read-only.
    src = await asyncpg.connect(args.source_dsn)
    try:
        rows = await src.fetch(
            "SELECT id, kind, title, raw_text, path FROM sources WHERE length(raw_text) > 200"
        )
    finally:
        await src.close()
    corpus = [dict(r) for r in rows]
    print(f"corpus: {len(corpus)} content sources; rewriting {len(rewrite_ids)} of them")

    # pgvector's type must exist before the pool's register_vector init hook runs
    # (mirrors db.get_pool's bootstrap) — a fresh eval DB doesn't have it yet.
    boot = await asyncpg.connect(args.eval_dsn)
    try:
        await boot.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await boot.close()

    pool = await asyncpg.create_pool(args.eval_dsn, init=register_vector)
    try:
        await apply_schema(pool)
        await pool.execute("TRUNCATE sources CASCADE")
        await pool.execute("DELETE FROM settings WHERE key LIKE 'legibility.%'")

        # --- baseline: legibility OFF, chunk from raw ------------------------
        for r in corpus:
            await store.upsert_source(
                pool, kind=r["kind"], title=r["title"], raw_text=r["raw_text"],
                path=r["path"], source_id=str(r["id"]),
            )
        baseline = await _measure(pool, probes, args.k)

        # --- treatment: enable legibility, force-rewrite the named dumps -----
        await set_setting(pool, LEGIBILITY_ENABLED_KEY, "true")
        await set_setting(pool, LEGIBILITY_MODE_KEY, "auto")
        for r in corpus:
            if str(r["id"]) in rewrite_ids:
                await store.upsert_source(
                    pool, kind=r["kind"], title=r["title"], raw_text=r["raw_text"],
                    path=r["path"], source_id=str(r["id"]), force_rewrite=True,
                )
        treatment = await _measure(pool, probes, args.k)

        # --- report ----------------------------------------------------------
        print(f"\n{'metric':14}{'baseline':>10}{'treatment':>12}{'delta':>10}")
        for key in ("recall@k", "precision@k", "mrr"):
            b, t = baseline[key], treatment[key]
            print(f"{key:14}{b:>10.4f}{t:>12.4f}{t - b:>+10.4f}")
        print(f"\nper-probe MRR (the within-dump discrimination signal):")
        for b, t in zip(baseline["per"], treatment["per"]):
            mark = "  <-- moved" if abs(t["rr"] - b["rr"]) > 1e-6 else ""
            print(f"  {b['rr']:.2f} -> {t['rr']:.2f}{mark}   {b['query'][:58]}")

        # Eyeball the rewrite for grounding (structural-only, no new claims).
        for rid in rewrite_ids:
            row = await pool.fetchrow(
                "SELECT title, rewrite_text, health FROM sources WHERE id=$1::uuid", rid
            )
            if row and row["rewrite_text"]:
                h = json.loads(row["health"]) if isinstance(row["health"], str) else row["health"]
                print(f"\n=== rewrite of {row['title']!r} (health score {h['score']}) ===")
                print(row["rewrite_text"])
                print(f"--- health notes: {h['notes']}")
                print(f"--- grounded: {h['grounded']}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
