"""The brain's network face — ONE app, TWO protocols (FastMCP shell).

- MCP (streamable HTTP at /mcp): tools `recall`, `profile`, `map`.
- Plain HTTP (custom routes): /health, /ingest, /recall, /profile, /map,
  /notion/pages (discovery: what the integration can see vs. what's ingested).

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

from .config import Config
from .db import apply_schema, close_pool, get_pool
from .notion import NotionError, fetch_page, list_pages
from .store import map_, profile, recall, source_ids, upsert_source

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
    if not isinstance(url, str):
        # A non-string url is a caller-fixable input error (400), not a 502 — else
        # parse_page_id raises a raw TypeError that the broad except leaks as 502.
        return JSONResponse({"error": "field 'url' must be a string"}, status_code=400)

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
        source_id, chunk_count = await upsert_source(
            pool,
            kind="notion_page",
            title=page["title"],
            raw_text=page["text"],
            path=page["path"],
            # Notion page id (a uuid) is the stable source id, so re-ingesting the
            # same URL wipe-replaces that source instead of creating a duplicate.
            source_id=page["id"],
            # Notion's real last-edited time (provenance), kept distinct from our
            # ingest/sync time (sources.updated_at).
            last_edited=page.get("last_edited_time"),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest: upsert_source failed")
        return JSONResponse({"error": f"ingest failed: {e}"}, status_code=500)

    # The page is split into sections — one chunk each; report the real count.
    return JSONResponse(
        {"source_id": source_id, "chunks": chunk_count, "path": page["path"], "title": page["title"]}
    )


@mcp.custom_route("/notion/pages", methods=["GET"])
async def notion_pages(_request: Request) -> JSONResponse:
    """GET /notion/pages — every Notion page shared with the integration (the
    discovery universe), each flagged `ingested` by checking its uuid against the
    sources table. Raw facts only — tree-building/presentation is the consumer's.
    """
    try:
        pages = await asyncio.to_thread(list_pages)
    except NotionError as e:
        # Missing token / API refusal — caller-visible config problem, so 400.
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001 — surface the cause, don't swallow it
        logger.exception("notion/pages: list_pages failed")
        return JSONResponse({"error": f"discovery failed: {e}"}, status_code=502)

    try:
        pool = await get_pool()
        ingested = await source_ids(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("notion/pages: source_ids failed")
        return JSONResponse({"error": f"discovery failed: {e}"}, status_code=502)

    for p in pages:
        p["ingested"] = p["id"] in ingested
    return JSONResponse({"pages": pages})


@mcp.custom_route("/recall", methods=["GET"])
async def recall_route(request: Request) -> JSONResponse:
    """GET /recall?q=&scope=&k=&complete= — hybrid-search sections, optionally
    scoped. Default top-k; pass `complete=true` to have the brain return
    everything IT judges relevant (the cutoff is the brain's own, k stays a
    safety cap — consumers never see a score scale)."""
    q = request.query_params.get("q")
    if not (q and q.strip()):
        return JSONResponse({"error": "missing required query param: q"}, status_code=400)
    scope = request.query_params.get("scope") or None
    # Clamp k to >=1 (and a sane cap) so k<=0 never reaches the `[:k]` slice.
    k = _int_param(request, "k", 12, lo=1, hi=100)
    # Opt-in: anything but an explicit true-ish value falls back to plain top-k.
    complete = request.query_params.get("complete") in ("1", "true")

    try:
        pool = await get_pool()
        chunks = await recall(pool, q, scope=scope, k=k, complete=complete)
    except Exception as e:  # noqa: BLE001 — embed/db failure: surface, don't 500
        logger.exception("recall failed")
        return JSONResponse({"error": f"recall failed: {e}"}, status_code=502)
    return JSONResponse({"chunks": [c.to_dict() for c in chunks]})


@mcp.custom_route("/profile", methods=["GET"])
async def profile_route(request: Request) -> JSONResponse:
    """GET /profile?scope=&budget= — the assembled domain dump for a path scope."""
    scope = request.query_params.get("scope")
    if not (scope and scope.strip()):
        return JSONResponse(
            {"error": "missing required query param: scope"}, status_code=400
        )
    # Parse only; the store core treats budget<=0 as "use the default", so a
    # garbage/negative budget never artificially flips the degrade gate.
    budget = _int_param(request, "budget", 20_000)
    focus = request.query_params.get("focus") or None

    try:
        pool = await get_pool()
        ctx = await profile(pool, scope, budget=budget, focus=focus)
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


def _int_param(
    request: Request,
    name: str,
    default: int,
    *,
    lo: int | None = None,
    hi: int | None = None,
) -> int:
    """Parse an int query param, falling back to `default` on missing/garbage,
    then clamp into `[lo, hi]` (either bound optional) so out-of-range values
    (e.g. k<=0 or budget<=0) can never reach the slice/gate that consumes them."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


# ---- MCP tools (US-009): same store functions, contract shapes ---------------

@mcp.tool(name="recall")
async def recall_tool(
    query: str, scope: str | None = None, k: int = 12, complete: bool = False
) -> dict:
    """Targeted hybrid retrieval — sections matching `query`, optionally within a
    path subtree (`scope`, e.g. 'Career/Job Search'). Default returns the top-k;
    pass `complete=true` to have the brain return everything IT judges relevant
    (its own cutoff, k as a safety cap). Returns
    {"chunks": [{heading, text, score, path}, ...]}."""
    # Guard empty input here too — the HTTP route does, and without this the MCP
    # face would leak a raw embedder error instead of a clear "query required".
    if not (query and query.strip()):
        raise ValueError("query is required")
    try:
        pool = await get_pool()
        chunks = await recall(pool, query, scope=scope, k=k, complete=complete)
    except Exception as e:  # noqa: BLE001 — embed/db failure: clear tool error
        logger.exception("recall (mcp) failed")
        raise RuntimeError(f"recall failed: {e}") from e
    return {"chunks": [c.to_dict() for c in chunks]}


@mcp.tool(name="profile")
async def profile_tool(
    scope: str, budget: int = 20_000, focus: str | None = None
) -> dict:
    """Domain dump — every section under the `scope` path prefix, assembled into
    structured markdown. `focus` is an optional query that, only when the dump is
    over budget, picks which sections survive the degrade. Returns the Context
    contract {"text", "sources", "truncated"}."""
    # Same empty-arg guard the HTTP route has — keep the two faces in parity
    # (without it, profile('') returns a silent empty Context).
    if not (scope and scope.strip()):
        raise ValueError("scope is required")
    try:
        pool = await get_pool()
        ctx = await profile(pool, scope, budget=budget, focus=focus)
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
        # Fail loud at boot on missing required config (e.g. VOYAGE_API_KEY) — else
        # the brain boots 'healthy' (/health is liveness-only) and 502s per request,
        # and pwa gates on brain health, so a silent misconfig would cascade.
        Config().validate()
        pool = await get_pool()
        try:
            # Inside the try so a failing apply_schema still closes the pool —
            # otherwise the module-global _pool stays set to an open pool.
            await apply_schema(pool)  # idempotent DDL — ensures sources/chunks exist on a fresh DB
            logger.info("brain: asyncpg pool opened + schema applied")
            async with inner(app):
                yield
        finally:
            await close_pool()
            logger.info("brain: asyncpg pool closed")

    app.router.lifespan_context = lifespan


_with_pool_lifespan(app)
