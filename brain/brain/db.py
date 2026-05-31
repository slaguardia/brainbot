"""Postgres connection: ONE asyncpg pool, built lazily from PG_DSN.

pgvector's type adapter is registered on every connection (via the pool's
`init` hook) so `vector(...)` columns round-trip as Python lists transparently.

This module owns the pool only. The DDL / apply_schema lives in the next task.
"""

from __future__ import annotations

import asyncio

import asyncpg
from pgvector.asyncpg import register_vector

from .config import Config

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
                _pool = await asyncpg.create_pool(Config().pg_dsn, init=_register)
    return _pool


async def close_pool() -> None:
    """Close the pool and clear the singleton (idempotent — safe if never opened)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
