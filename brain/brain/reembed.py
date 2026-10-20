"""Re-embed every chunk with the configured embedder — the migration to run after
changing BRAIN_EMBED_MODEL / BRAIN_EMBED_DIM (apply_schema refuses to boot until
the stored column matches).

    python -m brain.reembed

Embeds everything FIRST (the slow, failure-prone part), then swaps the column in
ONE transaction: retype chunks.embedding to vector(EMBED_DIM), write the new
vectors, restore NOT NULL + the HNSW index. Any failure leaves the old vectors
untouched. Run it with the brain stopped; a chunk inserted mid-run would be left
NULL, which the NOT NULL restore rejects — aborting the swap rather than storing
a hole.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg
from pgvector.asyncpg import register_vector

from .config import EMBED_DIM, Config
from .db import stored_embed_dim
from .embed import embed
from .store import _embed_input

logger = logging.getLogger("brain.reembed")

_BATCH = 32


async def main() -> None:
    conn = await asyncpg.connect(Config().pg_dsn)
    try:
        await register_vector(conn)
        rows = await conn.fetch("SELECT id, heading, text FROM chunks ORDER BY id")
        vectors: list[list[float]] = []
        for i in range(0, len(rows), _BATCH):
            batch = rows[i : i + _BATCH]
            vectors += embed([_embed_input(r["heading"] or "", r["text"]) for r in batch])
            logger.info("embedded %d/%d chunks", len(vectors), len(rows))

        old_dim = await stored_embed_dim(conn)
        async with conn.transaction():
            await conn.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw")
            await conn.execute(
                f"ALTER TABLE chunks ALTER COLUMN embedding DROP NOT NULL, "
                f"ALTER COLUMN embedding TYPE vector({EMBED_DIM}) USING NULL"
            )
            await conn.executemany(
                "UPDATE chunks SET embedding = $2 WHERE id = $1",
                [(r["id"], v) for r, v in zip(rows, vectors)],
            )
            await conn.execute("ALTER TABLE chunks ALTER COLUMN embedding SET NOT NULL")
            await conn.execute(
                "CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
            )
        logger.info(
            "re-embedded %d chunks: vector(%d) -> vector(%d) with %s",
            len(rows), old_dim, EMBED_DIM, Config().embed_model,
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
