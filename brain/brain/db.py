"""Postgres connection: ONE asyncpg pool, built lazily from PG_DSN.

pgvector's type adapter is registered on every connection (via the pool's
`init` hook) so `vector(...)` columns round-trip as Python lists transparently.

This module owns the pool AND the schema (`apply_schema`). The DDL is the one in
the plan's "Tech stack" section: two tables (sources + chunks) plus the four
indexes (HNSW, GIN, path-prefix, source/position). It is fully idempotent
(IF NOT EXISTS everywhere), so apply_schema is safe to run on every startup.
"""

from __future__ import annotations

import asyncio

import asyncpg
from pgvector.asyncpg import register_vector

from .config import EMBED_DIM, Config


# The full schema. Idempotent: CREATE EXTENSION/TABLE/INDEX ... IF NOT EXISTS.
# The chunks.embedding column dim is `EMBED_DIM` (voyage-3-lite = 512) — the
# single source of truth lives in config.py and is interpolated below so the
# column dim and the embedder can never drift apart. {dim} is the ONLY value
# substituted (a trusted int constant), so this f-string carries no SQL-injection
# surface.
_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind       text NOT NULL,
    title      text,
    raw_text   text NOT NULL,
    parent_id  uuid,
    path       text NOT NULL DEFAULT '',
    version    integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    source_last_edited timestamptz
);

-- The source's real last-edited time at its origin (e.g. Notion's
-- last_edited_time), distinct from updated_at (our ingest/sync time). Nullable:
-- unknown for sources whose origin doesn't supply it. Added idempotently so DBs
-- created before this column gain it on the next startup.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS source_last_edited timestamptz;

-- parent_id is the parent document's id AT THE ORIGIN (e.g. the Notion parent
-- page/database uuid) — provenance for /map's parent/child links, NOT a foreign
-- key. The parent may never have been synced, so the original inline FK would
-- reject valid ingests, and its ON DELETE CASCADE (drop a parent -> silently
-- delete child docs) is unwanted. Dropped idempotently so DBs created when the
-- FK was inline lose it on the next startup; a no-op everywhere else.
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_parent_id_fkey;

CREATE TABLE IF NOT EXISTS chunks (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id  uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    heading    text,
    text       text NOT NULL,
    position   integer NOT NULL,
    embedding  vector({dim}) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    fts        tsvector GENERATED ALWAYS AS
                 (to_tsvector('english', coalesce(heading,'') || ' ' || text)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_fts_gin
    ON chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS sources_path_prefix
    ON sources (path text_pattern_ops);
CREATE INDEX IF NOT EXISTS chunks_source_pos
    ON chunks (source_id, position);
""".format(dim=EMBED_DIM)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def _register(conn: asyncpg.Connection) -> None:
    """Per-connection init: teach asyncpg the pgvector `vector` type so embeddings
    pass as plain Python lists in both directions."""
    await register_vector(conn)


async def get_pool() -> asyncpg.Pool:
    """Return the process-wide asyncpg pool, creating it on first use.

    Lazy + locked so concurrent first-callers don't race to build two pools.
    """
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                dsn = Config().pg_dsn
                # The pgvector `vector` type must exist BEFORE the pool's init hook
                # runs register_vector (it introspects public.vector). On a fresh DB
                # the extension isn't created yet, so ensure it on a one-off
                # connection first — otherwise pool creation fails with
                # "unknown type: public.vector". apply_schema re-runs it idempotently.
                bootstrap = await asyncpg.connect(dsn)
                try:
                    await bootstrap.execute("CREATE EXTENSION IF NOT EXISTS vector")
                finally:
                    await bootstrap.close()
                _pool = await asyncpg.create_pool(dsn, init=_register)
    return _pool


async def close_pool() -> None:
    """Close the pool and clear the singleton (idempotent — safe if never opened)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema(pool: asyncpg.Pool) -> None:
    """Run the full DDL idempotently — extension, the sources + chunks tables, and
    the four indexes (HNSW semantic, GIN lexical, path-prefix scope, source/position
    for wipe-replace + ordered profile dumps). Safe to call on every startup."""
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
