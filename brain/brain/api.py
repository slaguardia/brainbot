"""The brain's network face — ONE app, TWO protocols (FastMCP shell).

- MCP (streamable HTTP at /mcp): tools `recall`, `doc`, `profile`, `map`.
- Plain HTTP (custom routes): /health, /ingest, /recall, /doc, /profile, /map,
  /notion/pages (discovery: what the integration can see vs. what's ingested).

Both faces are thin: they parse input, call the same `store` functions, and
return the contract shapes (`Chunk` / `Context` / the document / the source
tree) as JSON. graphiti is gone — this is the pgvector document substrate. The
app opens a single asyncpg pool on startup and closes it on shutdown (see the
lifespan).

Run: `uvicorn brain.api:app` (app = the Starlette app FastMCP builds).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Config
from .db import apply_schema, close_pool, get_pool
from .notion import NotionError, fetch_page, list_pages, verify_token
from .settings import NOTION_TOKEN_KEY, delete_setting, get_setting, set_setting
from .store import doc, map_, profile, recall, sources_last_edited, upsert_source

logger = logging.getLogger(__name__)


mcp = FastMCP(
    "brain",
    instructions=(
        "Personal knowledge brain — a pgvector document store. Reads are "
        "recall (targeted hybrid search), doc (one whole document by stable "
        "id), profile (domain dump), and map (source tree: ids, titles, "
        "versions). All reads are read-only; writes come only from sources."
    ),
)


# ---- Plain HTTP routes -------------------------------------------------------

async def _active_notion_token(pool) -> tuple[str | None, str | None]:
    """The Notion token in effect and where it came from. A token stored from the
    Integrations UI ('db') wins over the NOTION_TOKEN env ('env'); neither set ->
    (None, None). Returning the source lets the UI show how Notion is connected
    (it never sees the token itself)."""
    db = await get_setting(pool, NOTION_TOKEN_KEY)
    if db:
        return db, "db"
    env = Config().notion_token
    if env:
        return env, "env"
    return None, None


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
        pool = await get_pool()
        token, _ = await _active_notion_token(pool)
        page = await asyncio.to_thread(fetch_page, url, token)
    except NotionError as e:
        # Token / URL / not-shared — caller-fixable, so 400.
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001 — surface the cause, don't swallow it
        logger.exception("ingest: fetch_page failed")
        return JSONResponse({"error": f"fetch failed: {e}"}, status_code=502)

    try:
        source_id, chunk_count = await upsert_source(
            pool,
            kind="notion_page",
            title=page["title"],
            raw_text=page["text"],
            path=page["path"],
            # Notion page id (a uuid) is the stable source id, so re-ingesting the
            # same URL wipe-replaces that source instead of creating a duplicate.
            source_id=page["id"],
            # The parent page/database id — the stable parent link /map serves.
            parent_id=page.get("parent_id"),
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
    sources table. Ingested pages also carry `ingested_last_edited` — the origin
    edit time the brain captured at ingest — so a consumer can compare it to
    Notion's current `last_edited_time` and spot stale copies. Raw facts only —
    tree-building/staleness-judging/presentation is the consumer's.
    """
    try:
        pool = await get_pool()
        token, _ = await _active_notion_token(pool)
        pages = await asyncio.to_thread(list_pages, token)
    except NotionError as e:
        # Missing token / API refusal — caller-visible config problem, so 400.
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001 — surface the cause, don't swallow it
        logger.exception("notion/pages: list_pages failed")
        return JSONResponse({"error": f"discovery failed: {e}"}, status_code=502)

    try:
        ingested = await sources_last_edited(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("notion/pages: sources_last_edited failed")
        return JSONResponse({"error": f"discovery failed: {e}"}, status_code=502)

    for p in pages:
        p["ingested"] = p["id"] in ingested
        if p["ingested"]:
            # None for sources ingested before the edit time was recorded — the
            # consumer should treat those as possibly stale.
            p["ingested_last_edited"] = ingested[p["id"]]
    return JSONResponse({"pages": pages})


@mcp.custom_route("/integrations", methods=["GET"])
async def integrations(_request: Request) -> JSONResponse:
    """GET /integrations — connection status per integration, for the UI. Reports
    only whether Notion is connected and how ('db' = token set from the UI, 'env'
    = NOTION_TOKEN). Never returns the token itself."""
    try:
        pool = await get_pool()
        token, source = await _active_notion_token(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("integrations: status failed")
        return JSONResponse({"error": f"status failed: {e}"}, status_code=502)
    return JSONResponse({"notion": {"connected": bool(token), "source": source}})


@mcp.custom_route("/integrations/notion", methods=["PUT", "DELETE"])
async def notion_integration(request: Request) -> JSONResponse:
    """Manage the Notion integration token (the UI's connect/disconnect).

    PUT {token}: validate it against Notion (/users/me), then store it — a stored
    token overrides the NOTION_TOKEN env. Returns {connected, source, bot,
    workspace}; 400 if Notion rejects the token.
    DELETE: drop the stored token, falling back to the env token if one is set.
    Returns the resulting {connected, source}."""
    pool = await get_pool()

    if request.method == "DELETE":
        try:
            await delete_setting(pool, NOTION_TOKEN_KEY)
            token, source = await _active_notion_token(pool)
        except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
            logger.exception("integrations: disconnect failed")
            return JSONResponse({"error": f"disconnect failed: {e}"}, status_code=502)
        return JSONResponse({"connected": bool(token), "source": source})

    # PUT
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON {token}"}, status_code=400)
    token = (body or {}).get("token")
    if not token or not isinstance(token, str) or not token.strip():
        return JSONResponse({"error": "missing required field: token"}, status_code=400)

    try:
        info = await asyncio.to_thread(verify_token, token)
    except NotionError as e:
        # Notion rejected the token (empty / 401) — caller-fixable, so 400.
        return JSONResponse({"error": f"Notion rejected the token: {e}"}, status_code=400)
    except Exception as e:  # noqa: BLE001 — surface the cause, don't swallow it
        logger.exception("integrations: verify_token failed")
        return JSONResponse({"error": f"verify failed: {e}"}, status_code=502)

    try:
        await set_setting(pool, NOTION_TOKEN_KEY, token.strip())
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("integrations: store token failed")
        return JSONResponse({"error": f"store failed: {e}"}, status_code=502)

    return JSONResponse({"connected": True, "source": "db", **info})


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


@mcp.custom_route("/doc", methods=["GET"])
async def doc_route(request: Request) -> JSONResponse:
    """GET /doc?id=<stable-source-id> — one whole document, deterministically:
    {id, title, path, version, text}. `text` is the stored document verbatim;
    `version` is the content stamp to cache on. 400 on a missing/malformed id,
    404 on an unknown one."""
    doc_id = _id_param(request)
    if doc_id is None:
        return JSONResponse(
            {"error": "query param 'id' must be a document uuid"}, status_code=400
        )
    try:
        pool = await get_pool()
        document = await doc(pool, doc_id)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("doc failed")
        return JSONResponse({"error": f"doc failed: {e}"}, status_code=502)
    if document is None:
        return JSONResponse({"error": f"no document with id {doc_id}"}, status_code=404)
    return JSONResponse(document)


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
    """GET /map?scope= — the source tree under the scope (or all):
    {id, title, path, parent_id, version} per source. The discovery surface —
    where a consumer finds the stable ids to pin and the versions to diff."""
    scope = request.query_params.get("scope") or None
    try:
        pool = await get_pool()
        tree = await map_(pool, scope)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("map failed")
        return JSONResponse({"error": f"map failed: {e}"}, status_code=502)
    return JSONResponse({"sources": tree})


def _id_param(request: Request) -> str | None:
    """Parse the `id` query param as a document uuid, returning the canonical
    dashed form — or None on missing/malformed (the route 400s). Liberal in
    what it accepts (dashed or undashed hex), canonical in what it passes on."""
    raw = request.query_params.get("id")
    if not (raw and raw.strip()):
        return None
    try:
        return str(uuid.UUID(raw.strip()))
    except ValueError:
        return None


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
    {"chunks": [{id, heading, text, score, path}, ...]} — `id` is the owning
    document's stable id (escalate to the whole document with `doc`)."""
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


@mcp.tool(name="doc")
async def doc_tool(id: str) -> dict:
    """One whole document by stable id, deterministically — the stored text
    VERBATIM (not chunks), plus title/path and the content `version` stamp to
    cache on. Returns {id, title, path, version, text}. Raises on a malformed
    or unknown id."""
    # Same liberal-in/canonical-out id handling as the HTTP route — parity.
    try:
        doc_id = str(uuid.UUID((id or "").strip()))
    except ValueError as e:
        raise ValueError("id must be a document uuid") from e
    try:
        pool = await get_pool()
        document = await doc(pool, doc_id)
    except Exception as e:  # noqa: BLE001 — db failure: clear tool error
        logger.exception("doc (mcp) failed")
        raise RuntimeError(f"doc failed: {e}") from e
    if document is None:
        raise ValueError(f"no document with id {doc_id}")
    return document


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
    """Discovery — the source tree under `scope` (or all sources): the stable
    ids to pin (see `doc`), display titles/paths, parent links, and the content
    `version` stamps to diff for cheap change detection. Returns
    {"sources": [{id, title, path, parent_id, version}, ...]}."""
    try:
        pool = await get_pool()
        tree = await map_(pool, scope)
    except Exception as e:  # noqa: BLE001 — db failure: clear tool error
        logger.exception("map (mcp) failed")
        raise RuntimeError(f"map failed: {e}") from e
    return {"sources": tree}


# ---- Periodic Notion sync ----------------------------------------------------

def _parse_iso(s: str) -> datetime:
    """ISO-8601 (incl. Notion's trailing 'Z') -> aware datetime, for comparing a
    Notion page's `last_edited_time` against the brain's captured edit time."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _is_stale(page: dict, ingested: dict[str, str | None]) -> bool:
    """Whether an already-ingested Notion page's brain copy is behind its origin —
    the backend twin of the PWA's isStale. Only pages in `ingested` (uuid ==
    source id) are candidates: this never flags pages a human hasn't pulled. A
    page with no url (databases) or no edit time can't be compared/re-ingested;
    a page ingested before edit times were recorded (None) is treated as stale."""
    pid = page["id"]
    if pid not in ingested:
        return False
    if not page.get("url") or not page.get("last_edited_time"):
        return False
    captured = ingested[pid]
    if captured is None:
        return True
    return _parse_iso(page["last_edited_time"]) > _parse_iso(captured)


async def _sync_stale_pages(pool) -> tuple[int, int]:
    """Re-ingest every ingested page whose Notion copy moved past the brain's.
    Returns (synced, failed). Reuses the same fetch + wipe-replace upsert as
    /ingest, so a re-sync is idempotent. No-ops when Notion isn't connected."""
    token, _ = await _active_notion_token(pool)
    if token is None:
        return (0, 0)
    pages = await asyncio.to_thread(list_pages, token)
    ingested = await sources_last_edited(pool)
    stale = [p for p in pages if _is_stale(p, ingested)]

    synced = failed = 0
    for p in stale:
        try:
            page = await asyncio.to_thread(fetch_page, p["url"], token)
            await upsert_source(
                pool,
                kind="notion_page",
                title=page["title"],
                raw_text=page["text"],
                path=page["path"],
                source_id=page["id"],
                parent_id=page.get("parent_id"),
                last_edited=page.get("last_edited_time"),
            )
            synced += 1
        except Exception:  # noqa: BLE001 — one bad page must not abort the sweep
            logger.exception("sync: re-ingest failed for %s", p.get("url"))
            failed += 1
    return (synced, failed)


async def _poll_loop(pool, interval: int) -> None:
    """Re-ingest stale pages every `interval` seconds until cancelled at shutdown.
    Sleeps first (don't hammer Notion at boot), and each tick is best-effort: a
    failure is logged and the loop sleeps on rather than dying."""
    logger.info("brain: notion poll loop started (every %ds)", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            synced, failed = await _sync_stale_pages(pool)
            if synced or failed:
                logger.info("brain: notion sync — %d re-ingested, %d failed", synced, failed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep the loop alive across tick failures
            logger.exception("brain: notion sync tick failed")


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
            interval = Config().poll_interval_seconds
            poll = asyncio.create_task(_poll_loop(pool, interval)) if interval > 0 else None
            try:
                async with inner(app):
                    yield
            finally:
                if poll is not None:
                    poll.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await poll
        finally:
            await close_pool()
            logger.info("brain: asyncpg pool closed")

    app.router.lifespan_context = lifespan


_with_pool_lifespan(app)
