"""The brain's network face — ONE app, TWO protocols (FastMCP shell).

- MCP (streamable HTTP at /mcp): tools, added in later tasks.
- Plain HTTP (custom routes): /health now; /ingest, /recall, /profile, /map
  added in later tasks.

This is the stripped clean shell: graphiti is gone. The app opens a single
asyncpg pool on startup and closes it on shutdown (see the lifespan below).

Run: `uvicorn brain.api:app` (app = the Starlette app FastMCP builds).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from .db import close_pool, get_pool

logger = logging.getLogger(__name__)


mcp = FastMCP(
    "brain",
    instructions=(
        "Personal knowledge brain — a pgvector document store. Reads are "
        "recall (targeted hybrid search), profile (domain dump), and map "
        "(source tree). Tools are added in later tasks."
    ),
)


# ---- Plain HTTP routes -------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    # Liveness only — the process is up. (The pool is opened by the lifespan.)
    return JSONResponse({"ok": True})


# The Starlette app FastMCP builds: serves /mcp (MCP) + the custom routes above.
app: Starlette = mcp.streamable_http_app()


def _with_pool_lifespan(app: Starlette) -> None:
    """Wrap the app's existing (MCP session-manager) lifespan so the asyncpg pool
    opens on startup and closes on shutdown, without clobbering FastMCP's own
    lifespan."""
    inner = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await get_pool()
        logger.info("brain: asyncpg pool opened")
        try:
            async with inner(app):
                yield
        finally:
            await close_pool()
            logger.info("brain: asyncpg pool closed")

    app.router.lifespan_context = lifespan


_with_pool_lifespan(app)
