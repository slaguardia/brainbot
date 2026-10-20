"""python -m brain.reembed — swaps every chunk's vector for the embedder's, in place."""

from __future__ import annotations

import asyncio

import asyncpg
from pgvector.asyncpg import register_vector

from brain import reembed
from brain.config import EMBED_DIM


def test_reembed_replaces_every_vector_and_keeps_index(clean_db, seed, monkeypatch):
    seed(title="A", text="# One\nalpha\n# Two\nbeta", path="A")
    seed(title="B", text="gamma", path="B")
    monkeypatch.setattr(reembed, "embed", lambda texts: [[0.5] * EMBED_DIM for _ in texts])

    asyncio.run(reembed.main())

    async def _check():
        conn = await asyncpg.connect(clean_db)
        try:
            await register_vector(conn)
            vecs = await conn.fetch("SELECT embedding FROM chunks")
            index = await conn.fetchval(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'chunks_embedding_hnsw'"
            )
            return vecs, index
        finally:
            await conn.close()

    vecs, index = asyncio.run(_check())
    assert len(vecs) >= 3 and all(r["embedding"].to_list() ==[0.5] * EMBED_DIM for r in vecs)
    assert "hnsw" in index
