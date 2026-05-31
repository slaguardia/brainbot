"""The brain's network face — ONE app, TWO protocols.

- MCP (streamable HTTP at /mcp): tools `recall` and `capture`, for Claude
  Code (its .mcp.json points here). This replaces the old standalone
  graphiti MCP server entirely.
- Plain HTTP (custom routes): /health, POST /capture, GET /recall — for the
  PWA backend and the Claude Code memory-injection hook.

Both faces share one Brain instance (built in the MCP lifespan). All logic
lives in service.py; this file is just wiring.

Run: `uvicorn brain.api:app` (app = the Starlette app FastMCP builds).
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server.fastmcp import FastMCP
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Config
from .service import Brain

logger = logging.getLogger(__name__)

# Connection-class failures that mean "the singleton's pool is bad", as opposed
# to a normal empty result or a bad request. graphiti/redis already retries
# transient blips internally (see build_graphiti); these surface only when a
# connection stays dead, which is our cue to rebuild the singleton.
_CONN_ERRORS = (RedisConnectionError, RedisTimeoutError)

# Lazy singleton. FastMCP's `lifespan` runs inside the MCP session context,
# not at ASGI startup, so it can't initialize state that the plain-HTTP
# custom routes need. Lazy-init-with-lock works uniformly for both faces.
_brain: Brain | None = None
_brain_lock = asyncio.Lock()


async def brain() -> Brain:
    global _brain
    if _brain is None:
        async with _brain_lock:
            if _brain is None:
                b = Brain(Config())
                await b.init()
                _brain = b
    return _brain


async def _rebuild_brain(stale: Brain) -> Brain:
    """Replace the singleton after a connection-class failure, so recovery no
    longer needs a manual process restart. Dedups concurrent rebuilds: only the
    caller still holding the `stale` instance rebuilds; others get the fresh one.
    """
    global _brain
    async with _brain_lock:
        if _brain is stale:
            _brain = None
            try:
                await stale.close()
            except Exception:
                logger.warning("error closing stale brain during rebuild", exc_info=True)
        if _brain is None:
            b = Brain(Config())
            await b.init()
            _brain = b
    return _brain


async def _read(op):
    """Run a READ op against the brain; on a connection-class error, rebuild the
    singleton once and retry. Safe to retry — reads have no side effects."""
    b = await brain()
    try:
        return await op(b)
    except _CONN_ERRORS:
        logger.warning("brain connection error on read; rebuilding singleton and retrying once", exc_info=True)
        b = await _rebuild_brain(b)
        return await op(b)


async def _write(op):
    """Run a WRITE op (capture); on a connection-class error, rebuild the
    singleton so the NEXT request is healthy, then re-raise. We do NOT retry:
    add_episode is non-idempotent (a fresh uuid per call), so an auto-retry could
    double-write. The caller decides whether to retry."""
    b = await brain()
    try:
        return await op(b)
    except _CONN_ERRORS:
        logger.warning("brain connection error on write; rebuilding singleton (not retrying)", exc_info=True)
        await _rebuild_brain(b)
        raise


mcp = FastMCP(
    "brain",
    instructions=(
        "Personal knowledge brain. Use `recall` to look up what the brain knows "
        "about the user (their goals, preferences, history, relationships) before "
        "answering. Use `capture` to durably store a new fact or thought."
    ),
)


# ---- MCP tools (Claude Code) -------------------------------------------------

@mcp.tool()
async def recall(query: str, limit: int = 20, debug: bool = False) -> dict:
    """Search the user's personal brain. Returns `facts` — scored entity-facts,
    each carrying `polarity` (positive/negative) and `strength` (hard/soft) so a
    negative or hard-held fact is legible without reading prose. The graph is the
    source of truth; reason over these facts.

    Args:
        query: what to look up (natural language).
        limit: max results.
        debug: when true, also returns `episodes` (the source captured bodies)
            for human tracing/provenance only — not a knowledge surface.
    """
    return await _read(lambda b: b.recall(query, limit=limit, debug=debug))


@mcp.tool()
async def capture(text: str) -> dict:
    """Store a thought or note into the user's personal brain (rewritten into
    faithful prose and ingested as one episode)."""
    return await _write(lambda b: b.capture(text))


@mcp.tool()
async def profile() -> dict:
    """Return the full record the brain holds about the user as a flat list of
    `facts` from the graph — every current fact, each carrying `polarity`
    (positive/negative) and `strength` (hard/soft). Use when you need the
    complete picture (including the user's hard-held facts and avoidances)
    rather than the answer to one targeted question."""
    return await _read(lambda b: b.profile())


# ---- Plain HTTP routes (PWA backend, injection hook) ------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    # Liveness only — the process is up. (Brain construction is lazy.)
    return JSONResponse({"ok": True})


@mcp.custom_route("/capture", methods=["POST"])
async def capture_http(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    text = (body.get("text") or "").strip() if isinstance(body, dict) else ""
    group_id = (body.get("group_id") or None) if isinstance(body, dict) else None
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    try:
        result = await _write(lambda b: b.capture(text, group_id=group_id))
        return JSONResponse(result, status_code=202)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@mcp.custom_route("/recall", methods=["GET"])
async def recall_http(request: Request) -> JSONResponse:
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return JSONResponse({"error": "q is required"}, status_code=400)
    try:
        limit = int(request.query_params.get("limit") or 20)
    except ValueError:
        limit = 20
    group_id = request.query_params.get("group_id") or None
    debug = (request.query_params.get("debug") or "").strip().lower() in ("1", "true", "yes", "on")
    out = await _read(lambda b: b.recall(q, limit=limit, group_id=group_id, debug=debug))
    payload = {"query": q, "facts": out["facts"], "fact_count": len(out["facts"])}
    if debug:
        payload["episodes"] = out["episodes"]
        payload["episode_count"] = len(out["episodes"])
    return JSONResponse(payload)


@mcp.custom_route("/profile", methods=["GET"])
async def profile_http(request: Request) -> JSONResponse:
    group_id = request.query_params.get("group_id") or None
    out = await _read(lambda b: b.profile(group_id=group_id))
    return JSONResponse({"count": len(out["facts"]), "facts": out["facts"]})


# The Starlette app FastMCP builds: serves /mcp (MCP) + the custom routes above.
app = mcp.streamable_http_app()
