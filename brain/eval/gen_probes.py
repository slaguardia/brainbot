"""Generate the embedder A/B probe set (probes_embedder.json) from the real corpus.

Samples N content sources (seeded, so reruns pick the same ones) and asks Claude
for two queries each that the source answers: a `natural` one and a `paraphrase`
that avoids the source's distinctive words (so keyword matching alone fails —
the case that separates embedders). Prepends the legacy probes.json as kind
`legacy`. The output quotes personal notes: it is gitignored — keep it that way.

Usage (in the brain image, on the brain network):
    python gen_probes.py --dsn postgresql://brain:PW@postgres:5432/brain \
        --n 40 --out probes_embedder.json        # needs ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import sys

import anthropic
import asyncpg

PROMPT = """Below is a note from someone's personal knowledge base. Write two search queries that this note answers, as the note's owner might type them weeks later when trying to find it.

1. "natural": a normal question or phrase about the note's main point.
2. "paraphrase": asks about the same thing but avoids the note's distinctive words and names — use synonyms and describe the idea instead, so matching on shared keywords alone would fail.

Each query: 5-15 words, about one specific idea in the note, not "summarize this note". Reply with only JSON: {{"natural": "...", "paraphrase": "..."}}

Title: {title}

{text}"""


async def _sources(dsn: str) -> list:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(
            "SELECT id::text, title, raw_text FROM sources WHERE length(raw_text) > 300 ORDER BY id"
        )
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default="probes_embedder.json")
    a = ap.parse_args()

    random.seed(42)
    sample = random.sample(list(asyncio.run(_sources(a.dsn))), a.n)
    client = anthropic.Anthropic()
    legacy = json.loads((pathlib.Path(__file__).parent / "probes.json").read_text())
    probes = [{**p, "kind": "legacy"} for p in legacy]
    for r in sample:
        msg = client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=300,
            messages=[{"role": "user", "content": PROMPT.format(title=r["title"], text=r["raw_text"][:6000])}],
        )
        t = msg.content[0].text
        q = json.loads(t[t.index("{") : t.rindex("}") + 1])
        for kind in ("natural", "paraphrase"):
            probes.append({"query": q[kind], "relevant": [r["id"]], "kind": kind, "note": r["title"]})
        print(f"{r['title'][:50]!r}: {q}", file=sys.stderr)
    pathlib.Path(a.out).write_text(json.dumps(probes, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
