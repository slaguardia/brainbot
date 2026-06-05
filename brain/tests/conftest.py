"""Shared harness for the brain service tests.

Tests run against a REAL pgvector Postgres: the headline guarantees here — the
byte-exact /doc round-trip and the version-stamp semantics — are claims about
asyncpg + Postgres + the JSON layer, so faking the DB would test nothing. The
Voyage embedder (the only nondeterministic external call) is replaced with a
deterministic fake.

Wiring:
- `PG_DSN` says which Postgres to use; the DB-backed tests SKIP cleanly when it
  is unset or unreachable. The suite never touches that DSN's own database:
  it derives a sibling `<dbname>_test` database — created with ENCODING 'UTF8'
  TEMPLATE template0, because the version stamp md5's the server-encoding bytes
  and the tests must pin the encoding production assumes — and repoints PG_DSN
  at it, so a DSN aimed at the live brain can never be truncated by a test.
- `clean_db` TRUNCATEs sources (cascading to chunks) before each test.
- `client` is a Starlette TestClient over the real app: requests exercise the
  real routes, store, pool, and JSON encode/decode end to end.
- Seeding helpers run via asyncio.run with their own short-lived pool, so they
  never share an event loop with the client's lifespan-owned pool.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from urllib.parse import urlsplit, urlunsplit

import pytest

from brain import store
from brain.config import EMBED_DIM


def _fake_embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Deterministic stand-in for the Voyage embedder: one EMBED_DIM vector per
    text, derived from its sha256 so distinct texts get distinct vectors.
    Encodes with surrogatepass so a lone-surrogate fixture passes THROUGH the
    embedder and fails at its real boundary (asyncpg's UTF-8 encode) — the
    fake must not mask what the storable-text test pins down."""
    out = []
    for t in texts:
        digest = hashlib.sha256(t.encode("utf-8", "surrogatepass")).digest()
        out.append([b / 255 for b in (digest * (EMBED_DIM // len(digest)))])
    return out


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch):
    """Replace the embedder everywhere (store reads the module global)."""
    monkeypatch.setattr(store, "embed", _fake_embed)


def _test_dsn() -> tuple[str, str] | None:
    """(admin_dsn, test_dsn): the configured PG_DSN and its `<dbname>_test`
    sibling. None when PG_DSN is unset (the DB-backed tests skip)."""
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        return None
    parts = urlsplit(dsn)
    name = parts.path.lstrip("/") or "brain"
    if not name.endswith("_test"):
        name = f"{name}_test"
    return dsn, urlunsplit(parts._replace(path=f"/{name}"))


async def _create_test_db(admin_dsn: str, test_db_name: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(admin_dsn, timeout=5)
    try:
        # Pin the encoding the version stamp depends on. template0 is required
        # to set an encoding explicitly; DuplicateDatabase means a prior run
        # already created it — fine.
        await conn.execute(
            f'CREATE DATABASE "{test_db_name}" ENCODING \'UTF8\' TEMPLATE template0'
        )
    except asyncpg.DuplicateDatabaseError:
        pass
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def test_db() -> str:
    """Create (once) the dedicated test database, apply the schema, and repoint
    PG_DSN at it for everything downstream. Skips the test when Postgres is
    unreachable or PG_DSN is unset."""
    dsns = _test_dsn()
    if dsns is None:
        pytest.skip("PG_DSN is unset — point it at a pgvector Postgres to run")
    admin_dsn, test_dsn = dsns
    test_db_name = urlsplit(test_dsn).path.lstrip("/")
    try:
        asyncio.run(_create_test_db(admin_dsn, test_db_name))
    except (OSError, asyncio.TimeoutError) as e:
        pytest.skip(f"postgres unreachable at PG_DSN: {e}")

    os.environ["PG_DSN"] = test_dsn
    # The app lifespan validates VOYAGE_API_KEY at boot; the embedder itself is
    # faked, so any non-empty value satisfies the boot check.
    os.environ.setdefault("VOYAGE_API_KEY", "test-key")

    async def _apply() -> None:
        import asyncpg

        from brain.db import apply_schema

        pool = await asyncpg.create_pool(test_dsn)
        try:
            await apply_schema(pool)
        finally:
            await pool.close()

    asyncio.run(_apply())
    return test_dsn


@pytest.fixture
def clean_db(test_db: str):
    """Fresh substrate per test: truncate sources (cascades to chunks)."""

    async def _truncate() -> None:
        import asyncpg

        conn = await asyncpg.connect(test_db)
        try:
            await conn.execute("TRUNCATE sources CASCADE")
        finally:
            await conn.close()

    asyncio.run(_truncate())
    return test_db


@pytest.fixture(scope="session")
def client(test_db):
    """The real app under a TestClient — entering the context runs the lifespan
    (pool + schema), so requests hit the full HTTP/JSON path. Session-scoped of
    necessity: FastMCP's StreamableHTTP session manager can only be run once
    per process, so the lifespan must not restart per test. Per-test isolation
    comes from `clean_db`, not from restarting the app."""
    from starlette.testclient import TestClient

    from brain.api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def mcp_call(clean_db):
    """Call an MCP tool coroutine (which reaches the db module's GLOBAL pool via
    get_pool) from a test. The session TestClient owns that global in ITS event
    loop, so this swaps the global out, lets the tool build a fresh pool in this
    call's own loop, closes it, and restores the client's — pools never cross
    loops."""

    def _call(tool, /, **kwargs):
        from brain import db

        saved = db._pool
        db._pool = None

        async def _go():
            try:
                return await tool(**kwargs)
            finally:
                await db.close_pool()

        try:
            return asyncio.run(_go())
        finally:
            db._pool = saved

    return _call


@pytest.fixture
def seed(clean_db, fake_embed):
    """seed(title=..., text=..., path=..., source_id=..., parent_id=...) -> id.
    Runs upsert_source with a short-lived pool of its own (own event loop —
    never shared with the client's)."""

    def _seed(
        *,
        title: str,
        text: str,
        path: str,
        source_id: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        async def _run() -> str:
            import asyncpg
            from pgvector.asyncpg import register_vector

            pool = await asyncpg.create_pool(clean_db, init=register_vector)
            try:
                src_id, _ = await store.upsert_source(
                    pool,
                    kind="notion_page",
                    title=title,
                    raw_text=text,
                    path=path,
                    source_id=source_id,
                    parent_id=parent_id,
                )
                return src_id
            finally:
                await pool.close()

        return asyncio.run(_run())

    return _seed
