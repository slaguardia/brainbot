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

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Config
from .service import Brain

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
async def recall(query: str, limit: int = 20) -> dict:
    """Search the user's personal brain. Returns `facts` (scored, precise
    entity-facts — but positive-only) and `episodes` (the faithful captured
    bodies, which include negatives and rules the facts may miss). For
    completeness, read `episodes`.

    Args:
        query: what to look up (natural language).
        limit: max results.
    """
    b = await brain()
    return await b.recall(query, limit=limit)


@mcp.tool()
async def capture(text: str) -> dict:
    """Store a thought or note into the user's personal brain (rewritten into
    faithful prose and ingested as one episode)."""
    b = await brain()
    return await b.capture(text)


@mcp.tool()
async def profile() -> list[dict]:
    """Return the full faithful record the brain holds about the user — every
    captured episode body (rewrites). Use when you need the complete picture
    (including the user's hard rules and avoid-lists) rather than the answer to
    one targeted question."""
    b = await brain()
    return await b.profile()


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
        b = await brain()
        return JSONResponse(await b.capture(text, group_id=group_id), status_code=202)
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
    b = await brain()
    out = await b.recall(q, limit=limit, group_id=group_id)
    return JSONResponse(
        {
            "query": q,
            "facts": out["facts"],
            "episodes": out["episodes"],
            "fact_count": len(out["facts"]),
            "episode_count": len(out["episodes"]),
        }
    )


@mcp.custom_route("/profile", methods=["GET"])
async def profile_http(request: Request) -> JSONResponse:
    group_id = request.query_params.get("group_id") or None
    b = await brain()
    episodes = await b.profile(group_id=group_id)
    return JSONResponse({"count": len(episodes), "episodes": episodes})


# The Starlette app FastMCP builds: serves /mcp (MCP) + the custom routes above.
app = mcp.streamable_http_app()
