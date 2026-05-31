"""The brain's network face — ONE app, TWO protocols (FastMCP shell).

- MCP (streamable HTTP at /mcp): tools `recall`, `profile`, `map`.
- Plain HTTP (custom routes): /health, /ingest, /recall, /profile, /map.

Both faces are thin: they parse input, call the same `store` functions, and
return the contract shapes (`Chunk` / `Context` / the source tree) as JSON.
graphiti is gone — this is the pgvector document substrate. The app opens a
single asyncpg pool on startup and closes it on shutdown (see the lifespan).

Run: `uvicorn brain.api:app` (app = the Starlette app FastMCP builds).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from .db import apply_schema, close_pool, get_pool
from .notion import NotionError, fetch_page
from .store import map_, profile, recall, upsert_source

logger = logging.getLogger(__name__)


mcp = FastMCP(
    "brain",
    instructions=(
        "Personal knowledge brain — a pgvector document store. Reads are "
        "recall (targeted hybrid search), profile (domain dump), and map "
        "(source tree). All reads are read-only; writes come only from sources."
    ),
)


# ---- Plain HTTP routes -------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    # Liveness only — the process is up. (The pool is opened by the lifespan.)
    return JSONResponse({"ok": True})


@mcp.custom_route("/ingest", methods=["POST"])
async def ingest(request: Request) -> JSONResponse:
    """POST /ingest {url} — fetch a Notion page, upsert it as a source, and
    re-derive its chunks (wipe-replace). Returns the source id + chunk count.

    Notion failures (no token, bad URL, page not shared) come back as clear 4xx
    errors rather than a 500."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON {url}"}, status_code=400)
    url = (body or {}).get("url")
    if not url:
        return JSONResponse({"error": "missing required field: url"}, status_code=400)

    try:
        page = await asyncio.to_thread(fetch_page, url)
    except NotionError as e:
        # Token / URL / not-shared — caller-fixable, so 400.
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001 — surface the cause, don't swallow it
        logger.exception("ingest: fetch_page failed")
        return JSONResponse({"error": f"fetch failed: {e}"}, status_code=502)

    try:
        pool = await get_pool()
        source_id = await upsert_source(
            pool,
            kind="notion_page",
            title=page["title"],
            raw_text=page["text"],
            path=page["path"],
            # Notion page id (a uuid) is the stable source id, so re-ingesting the
            # same URL wipe-replaces that source instead of creating a duplicate.
            source_id=page["id"],
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest: upsert_source failed")
        return JSONResponse({"error": f"ingest failed: {e}"}, status_code=500)

    # Phase 1: whole page = one chunk.
    return JSONResponse(
        {"source_id": source_id, "chunks": 1, "path": page["path"], "title": page["title"]}
    )


@mcp.custom_route("/recall", methods=["GET"])
async def recall_route(request: Request) -> JSONResponse:
    """GET /recall?q=&scope=&k= — top-k hybrid-search sections, optionally scoped."""
    q = request.query_params.get("q")
    if not q:
        return JSONResponse({"error": "missing required query param: q"}, status_code=400)
    scope = request.query_params.get("scope") or None
    k = _int_param(request, "k", 12)

    try:
        pool = await get_pool()
        chunks = await recall(pool, q, scope=scope, k=k)
    except Exception as e:  # noqa: BLE001 — embed/db failure: surface, don't 500
        logger.exception("recall failed")
        return JSONResponse({"error": f"recall failed: {e}"}, status_code=502)
    return JSONResponse({"chunks": [c.to_dict() for c in chunks]})


@mcp.custom_route("/profile", methods=["GET"])
async def profile_route(request: Request) -> JSONResponse:
    """GET /profile?scope=&budget= — the assembled domain dump for a path scope."""
    scope = request.query_params.get("scope")
    if not scope:
        return JSONResponse(
            {"error": "missing required query param: scope"}, status_code=400
        )
    budget = _int_param(request, "budget", 20_000)

    try:
        pool = await get_pool()
        ctx = await profile(pool, scope, budget=budget)
    except Exception as e:  # noqa: BLE001 — embed/db failure: surface, don't 500
        logger.exception("profile failed")
        return JSONResponse({"error": f"profile failed: {e}"}, status_code=502)
    return JSONResponse(ctx.to_dict())


@mcp.custom_route("/map", methods=["GET"])
async def map_route(request: Request) -> JSONResponse:
    """GET /map?scope= — the (path, title) source tree under the scope (or all)."""
    scope = request.query_params.get("scope") or None
    try:
        pool = await get_pool()
        tree = await map_(pool, scope)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("map failed")
        return JSONResponse({"error": f"map failed: {e}"}, status_code=502)
    return JSONResponse({"sources": tree})


def _int_param(request: Request, name: str, default: int) -> int:
    """Parse an int query param, falling back to `default` on missing/garbage."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ---- MCP tools (US-009): same store functions, contract shapes ---------------

@mcp.tool(name="recall")
async def recall_tool(query: str, scope: str | None = None, k: int = 12) -> dict:
    """Targeted hybrid retrieval — top-k sections matching `query`, optionally
    within a path subtree (`scope`, e.g. 'Career/Job Search'). Returns
    {"chunks": [{heading, text, score, path}, ...]}."""
    try:
        pool = await get_pool()
        chunks = await recall(pool, query, scope=scope, k=k)
    except Exception as e:  # noqa: BLE001 — embed/db failure: clear tool error
        logger.exception("recall (mcp) failed")
        raise RuntimeError(f"recall failed: {e}") from e
    return {"chunks": [c.to_dict() for c in chunks]}


@mcp.tool(name="profile")
async def profile_tool(scope: str, budget: int = 20_000) -> dict:
    """Domain dump — every section under the `scope` path prefix, assembled into
    structured markdown. Returns the Context contract
    {"text", "sources", "truncated"}."""
    try:
        pool = await get_pool()
        ctx = await profile(pool, scope, budget=budget)
    except Exception as e:  # noqa: BLE001 — embed/db failure: clear tool error
        logger.exception("profile (mcp) failed")
        raise RuntimeError(f"profile failed: {e}") from e
    return ctx.to_dict()


@mcp.tool(name="map")
async def map_tool(scope: str | None = None) -> dict:
    """Domain discovery — the (path, title) source tree under `scope` (or all
    sources). Returns {"sources": [{path, title}, ...]}."""
    try:
        pool = await get_pool()
        tree = await map_(pool, scope)
    except Exception as e:  # noqa: BLE001 — db failure: clear tool error
        logger.exception("map (mcp) failed")
        raise RuntimeError(f"map failed: {e}") from e
    return {"sources": tree}


# The Starlette app FastMCP builds: serves /mcp (MCP) + the custom routes above.
app: Starlette = mcp.streamable_http_app()


def _with_pool_lifespan(app: Starlette) -> None:
    """Wrap the app's existing (MCP session-manager) lifespan so the asyncpg pool
    opens on startup and closes on shutdown, without clobbering FastMCP's own
    lifespan."""
    inner = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        pool = await get_pool()
        await apply_schema(pool)  # idempotent DDL — ensures sources/chunks exist on a fresh DB
        logger.info("brain: asyncpg pool opened + schema applied")
        try:
            async with inner(app):
                yield
        finally:
            await close_pool()
            logger.info("brain: asyncpg pool closed")

    app.router.lifespan_context = lifespan


_with_pool_lifespan(app)
