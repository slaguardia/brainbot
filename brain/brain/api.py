"""The brain's network face — ONE app, TWO protocols (FastMCP shell).

- MCP (streamable HTTP at /mcp): tools `recall`, `doc`, `profile`, `map`.
- Plain HTTP (custom routes): /health, /ingest, /recall, /doc, /profile, /map,
  /changes (the Tier 0 change signal), /notion/pages (discovery: what the
  integration can see vs. what's ingested).

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

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Config
from .db import apply_schema, close_pool, get_pool
from .notion import NotionError, fetch_page, list_pages, verify_token
from .settings import (
    LEGIBILITY_ENABLED_KEY,
    LEGIBILITY_MODE_KEY,
    LEGIBILITY_MODEL_KEY,
    LEGIBILITY_THRESHOLD_KEY,
    NOTION_TOKEN_KEY,
    POLL_INTERVAL_KEY,
    _effective_legibility,
    delete_setting,
    get_setting,
    legibility_status,
    set_setting,
)
from .store import (
    _parse_iso,
    change_cursor,
    delete_source,
    doc,
    map_,
    profile,
    recall,
    set_rewrite_policy,
    source_for_rewrite,
    sources_last_edited,
    upsert_source,
)

logger = logging.getLogger(__name__)

# Set when the poll interval is changed from the UI, so the running poll loop
# wakes from its sleep and re-reads the new interval instead of waiting out the
# old one. Lives in the app's single event loop alongside the loop and routes.
_poll_reconfig = asyncio.Event()


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


async def _effective_poll_interval(pool) -> tuple[int, str]:
    """Seconds between Notion sync sweeps and where the value came from. A value
    stored from the UI ('db') wins over BRAIN_POLL_INTERVAL_SECONDS ('env'); 0
    (from either) means the loop idles. A malformed stored value is ignored in
    favour of env so a bad row can't wedge syncing off."""
    db = await get_setting(pool, POLL_INTERVAL_KEY)
    if db is not None:
        try:
            return max(0, int(db)), "db"
        except ValueError:
            pass
    return Config().poll_interval_seconds, "env"


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


@mcp.custom_route("/sources/{source_id}", methods=["DELETE"])
async def delete_source_route(request: Request) -> JSONResponse:
    """DELETE /sources/{id} — un-ingest a source: drop the source row and its
    chunks (ON DELETE CASCADE). The inverse of /ingest. Returns {deleted: bool}
    — False (still 200) when no source had that id, so revoking twice is safe.
    A non-uuid id is a caller-fixable 400."""
    source_id = request.path_params["source_id"]
    try:
        uuid.UUID(source_id)
    except (ValueError, AttributeError, TypeError):
        return JSONResponse({"error": "id must be a uuid"}, status_code=400)

    try:
        pool = await get_pool()
        deleted = await delete_source(pool, source_id)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("sources: delete failed")
        return JSONResponse({"error": f"delete failed: {e}"}, status_code=502)
    return JSONResponse({"deleted": deleted})


@mcp.custom_route("/sources/{source_id}/rewrite", methods=["GET", "POST"])
async def rewrite_source_route(request: Request) -> JSONResponse:
    """The note-legibility manual surface for one source (docs/note-legibility.md).

    GET /sources/{id}/rewrite — owner READ for the dashboard diff view: the stored
    {id, raw_text, rewrite_text, health, rewrite_policy} so a diff (raw vs rewrite)
    renders from the columns without re-running the LLM. 404 if no such source.
    (raw_text is duplicated from doc() here on purpose — this is owner tooling, not
    the consumer doc contract.)

    POST /sources/{id}/rewrite — the manual TRIGGER. Re-analyzes the source's
    ALREADY-STORED raw_text and re-derives its chunks via
    `upsert_source(force_rewrite=True)` — re-fetching nothing — so it reuses the
    whole ingest path (analyze -> chunk_source fork -> embed -> wipe-replace).
    `force_rewrite` bypasses both the auto-threshold check and the analysis-hash
    cache, so it rewrites even in manual mode and even on unchanged text. Returns
    {id, health, rewrote, chunk_count}.

    POST precedence (the two real decisions):
    - The feature globally disabled -> 409 {rewrote: false}. There is no per-page
      path that runs the analyzer while legibility is off.
    - The source pinned `rewrite_policy='off'` -> 200 {rewrote: false} with a
      reason (NOT a 4xx): 'off' is a deliberate human choice an explicit request
      must not silently override. Clear the pin first (PUT .../rewrite-policy).
    """
    source_id = request.path_params["source_id"]
    try:
        uuid.UUID(source_id)
    except (ValueError, AttributeError, TypeError):
        return JSONResponse({"error": "id must be a uuid"}, status_code=400)

    if request.method == "GET":
        try:
            pool = await get_pool()
            rec = await source_for_rewrite(pool, source_id)
        except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
            logger.exception("sources: rewrite read failed")
            return JSONResponse({"error": f"read failed: {e}"}, status_code=502)
        if rec is None:
            return JSONResponse({"error": f"no source with id {source_id}"}, status_code=404)
        return JSONResponse(
            {
                "id": source_id,
                "raw_text": rec["raw_text"],
                "rewrite_text": rec["rewrite_text"],
                "health": rec["health"],
                "rewrite_policy": rec["rewrite_policy"],
            }
        )

    try:
        pool = await get_pool()
        enabled, _mode, _threshold, _model = await _effective_legibility(pool)
        if not enabled:
            # Globally off (toggle false, or enabled-but-no-key) — never analyze.
            return JSONResponse(
                {"id": source_id, "rewrote": False, "health": None,
                 "reason": "legibility disabled"},
                status_code=409,
            )
        rec = await source_for_rewrite(pool, source_id)
        if rec is None:
            return JSONResponse({"error": f"no source with id {source_id}"}, status_code=404)
        if rec["rewrite_policy"] == "off":
            return JSONResponse(
                {"id": source_id, "rewrote": False, "health": rec["health"],
                 "reason": "pinned to raw (rewrite_policy=off) — clear the pin first"}
            )
        _, chunk_count = await upsert_source(
            pool,
            kind=rec["kind"],
            title=rec["title"],
            raw_text=rec["raw_text"],
            path=rec["path"],
            source_id=source_id,
            parent_id=rec["parent_id"],
            last_edited=rec["last_edited"],
            force_rewrite=True,
        )
        after = await source_for_rewrite(pool, source_id)
    except Exception as e:  # noqa: BLE001 — analyze/embed/db failure: surface, don't 500 silently
        logger.exception("sources: rewrite failed")
        return JSONResponse({"error": f"rewrite failed: {e}"}, status_code=502)
    # `rewrote` reflects whether a rewrite actually landed: false if the analysis
    # degraded to pass-through (e.g. a transient LLM failure).
    return JSONResponse(
        {
            "id": source_id,
            "health": after["health"] if after else None,
            "rewrote": bool(after and after["rewrite_text"] is not None),
            "chunk_count": chunk_count,
        }
    )


@mcp.custom_route("/sources/{source_id}/rewrite-policy", methods=["PUT"])
async def rewrite_policy_route(request: Request) -> JSONResponse:
    """PUT /sources/{id}/rewrite-policy {policy} — set a source's per-source
    legibility override: 'auto' (follow the global policy), 'manual' (analyze for
    health but rewrite only on explicit request), or 'off' (pin to the raw voice —
    never rewrite, even by the manual endpoint). Returns {id, rewrite_policy}; 404
    if no such source, 400 on an invalid policy."""
    source_id = request.path_params["source_id"]
    try:
        uuid.UUID(source_id)
    except (ValueError, AttributeError, TypeError):
        return JSONResponse({"error": "id must be a uuid"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON {policy}"}, status_code=400)
    policy = (body or {}).get("policy")
    if policy not in ("auto", "off", "manual"):
        return JSONResponse(
            {"error": "field 'policy' must be one of: auto, off, manual"}, status_code=400
        )

    try:
        pool = await get_pool()
        updated = await set_rewrite_policy(pool, source_id, policy)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("sources: set rewrite_policy failed")
        return JSONResponse({"error": f"set policy failed: {e}"}, status_code=502)
    if not updated:
        return JSONResponse({"error": f"no source with id {source_id}"}, status_code=404)
    return JSONResponse({"id": source_id, "rewrite_policy": policy})


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
    try:
        interval, isource = await _effective_poll_interval(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("integrations: poll interval read failed")
        return JSONResponse({"error": f"status failed: {e}"}, status_code=502)
    try:
        legibility = await legibility_status(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("integrations: legibility status read failed")
        return JSONResponse({"error": f"status failed: {e}"}, status_code=502)
    return JSONResponse(
        {
            "notion": {"connected": bool(token), "source": source},
            "sync": {"interval_seconds": interval, "source": isource},
            # The note-legibility policy, for the UI's settings card. `active` =
            # actually running (enabled AND key present); `has_key` lets the UI warn
            # when the toggle is on but the secret is missing. Never the key itself.
            "legibility": legibility,
        }
    )


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


@mcp.custom_route("/integrations/notion/sync", methods=["PUT", "DELETE"])
async def notion_sync_setting(request: Request) -> JSONResponse:
    """Manage the automatic Notion sync interval (the UI's auto-sync control).

    PUT {interval_seconds}: store the interval (0 = off) — it overrides the
    BRAIN_POLL_INTERVAL_SECONDS env. DELETE: drop the stored value, falling back
    to the env interval. Both wake the running poll loop so the change takes
    effect without a restart, and return the resulting {interval_seconds, source}."""
    pool = await get_pool()

    if request.method == "DELETE":
        try:
            await delete_setting(pool, POLL_INTERVAL_KEY)
        except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
            logger.exception("integrations: sync interval reset failed")
            return JSONResponse({"error": f"reset failed: {e}"}, status_code=502)
    else:  # PUT
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "body must be JSON {interval_seconds}"}, status_code=400
            )
        raw = (body or {}).get("interval_seconds")
        try:
            interval = int(raw)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "field 'interval_seconds' must be an integer"}, status_code=400
            )
        if interval < 0:
            return JSONResponse(
                {"error": "field 'interval_seconds' must be >= 0 (0 disables sync)"},
                status_code=400,
            )
        try:
            await set_setting(pool, POLL_INTERVAL_KEY, str(interval))
        except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
            logger.exception("integrations: sync interval store failed")
            return JSONResponse({"error": f"store failed: {e}"}, status_code=502)

    # Wake the poll loop to pick up the new interval immediately.
    _poll_reconfig.set()
    try:
        eff, source = await _effective_poll_interval(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("integrations: sync interval read-back failed")
        return JSONResponse({"error": f"read failed: {e}"}, status_code=502)
    return JSONResponse({"interval_seconds": eff, "source": source})


@mcp.custom_route("/integrations/legibility", methods=["PUT", "DELETE"])
async def legibility_setting(request: Request) -> JSONResponse:
    """Manage the note-legibility policy (the UI's settings card) — the runtime
    `legibility.*` rows, toggleable without a restart exactly like the Notion poll
    interval. The SECRET (ANTHROPIC_API_KEY) is NOT managed here; it's env-only.

    PUT {enabled?, mode?, threshold?, model?}: store any provided field (partial
    updates allowed). DELETE: drop all four rows, reverting to the defaults
    (disabled = today's behavior). Both return the resulting legibility status
    (the same shape GET /integrations carries under `legibility`)."""
    pool = await get_pool()

    if request.method == "DELETE":
        try:
            for key in (
                LEGIBILITY_ENABLED_KEY,
                LEGIBILITY_MODE_KEY,
                LEGIBILITY_THRESHOLD_KEY,
                LEGIBILITY_MODEL_KEY,
            ):
                await delete_setting(pool, key)
        except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
            logger.exception("integrations: legibility reset failed")
            return JSONResponse({"error": f"reset failed: {e}"}, status_code=502)
        return JSONResponse(await legibility_status(pool))

    # PUT — validate each provided field, then store it.
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "body must be JSON {enabled?, mode?, threshold?, model?}"},
            status_code=400,
        )
    body = body or {}
    updates: list[tuple[str, str]] = []

    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            return JSONResponse({"error": "field 'enabled' must be a boolean"}, status_code=400)
        updates.append((LEGIBILITY_ENABLED_KEY, "true" if body["enabled"] else "false"))
    if "mode" in body:
        if body["mode"] not in ("auto", "manual"):
            return JSONResponse(
                {"error": "field 'mode' must be 'auto' or 'manual'"}, status_code=400
            )
        updates.append((LEGIBILITY_MODE_KEY, body["mode"]))
    if "threshold" in body:
        try:
            threshold = int(body["threshold"])
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "field 'threshold' must be an integer"}, status_code=400
            )
        if not 0 <= threshold <= 100:
            return JSONResponse(
                {"error": "field 'threshold' must be in 0..100"}, status_code=400
            )
        updates.append((LEGIBILITY_THRESHOLD_KEY, str(threshold)))
    if "model" in body:
        if not isinstance(body["model"], str) or not body["model"].strip():
            return JSONResponse({"error": "field 'model' must be a non-empty string"}, status_code=400)
        updates.append((LEGIBILITY_MODEL_KEY, body["model"].strip()))

    if not updates:
        return JSONResponse(
            {"error": "no recognized fields (enabled, mode, threshold, model)"},
            status_code=400,
        )

    try:
        for key, value in updates:
            await set_setting(pool, key, value)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("integrations: legibility store failed")
        return JSONResponse({"error": f"store failed: {e}"}, status_code=502)
    return JSONResponse(await legibility_status(pool))


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


@mcp.custom_route("/changes", methods=["GET"])
async def changes_route(request: Request) -> JSONResponse:
    """GET /changes?since=<cursor> — the Tier 0 change signal. Returns the current
    opaque change `cursor` over all sources and whether it differs from `since`:
    {cursor, changed}. `changed` is true when `since` is absent or stale, false
    when it matches — so a caching consumer polls this one cheap query and only
    does expensive work when `changed` flips true. Read-only; writes nothing."""
    since = request.query_params.get("since")
    try:
        pool = await get_pool()
        cursor = await change_cursor(pool)
    except Exception as e:  # noqa: BLE001 — db failure: surface, don't 500
        logger.exception("changes failed")
        return JSONResponse({"error": f"changes failed: {e}"}, status_code=502)
    return JSONResponse({"cursor": cursor, "changed": since != cursor})


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


async def _poll_loop(pool) -> None:
    """Re-ingest stale pages on the effective interval until cancelled at shutdown.
    The interval is re-read each cycle (so a UI change takes effect without a
    restart) and the sleep wakes early on a reconfig. An interval of 0 idles the
    loop until it's re-enabled. Sleeps before the first sync (don't hammer Notion
    at boot), and each tick is best-effort: a failure is logged and the loop
    sleeps on rather than dying."""
    logger.info("brain: notion poll loop started")
    while True:
        interval, _ = await _effective_poll_interval(pool)
        _poll_reconfig.clear()
        if interval <= 0:
            # Disabled — idle until the interval is changed from the UI.
            await _poll_reconfig.wait()
            continue
        try:
            # Sleep the interval, but wake early (and re-read it) on a reconfig.
            await asyncio.wait_for(_poll_reconfig.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass  # the interval elapsed → run a sweep
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
            # Always start the loop; it idles when the effective interval is 0 and
            # can be enabled from the UI without a restart.
            poll = asyncio.create_task(_poll_loop(pool))
            try:
                async with inner(app):
                    yield
            finally:
                poll.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poll
        finally:
            await close_pool()
            logger.info("brain: asyncpg pool closed")

    app.router.lifespan_context = lifespan


_with_pool_lifespan(app)
