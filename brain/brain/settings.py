"""Runtime settings in Postgres — config the UI manages, not deploy-time env.

A tiny key/value store (the `settings` table lives in db.py's schema). It holds
runtime toggles the owner flips from the UI without a redeploy: the Notion
integration token, the auto-sync poll interval, and the note-legibility policy
(`legibility.*`).

Token values are secrets — these helpers never log them, and the API layer never
returns a stored token to the client. A DB-stored token takes precedence over the
NOTION_TOKEN env var (see api._active_notion_token); deleting it falls back to env.

The split that matters for legibility: the on/off TOGGLE and its knobs live here
(runtime, UI-managed); the SECRET (ANTHROPIC_API_KEY) lives in env/Config. See
`_effective_legibility` for how the two resolve at ingest time.
"""

from __future__ import annotations

import logging

import asyncpg

from .config import Config

logger = logging.getLogger(__name__)

# The settings keys in use today.
NOTION_TOKEN_KEY = "notion_token"
# Seconds between automatic Notion sync sweeps, set from the UI. A stored value
# overrides BRAIN_POLL_INTERVAL_SECONDS (env); "0" explicitly disables the loop.
POLL_INTERVAL_KEY = "notion_poll_interval"

# Note-legibility policy (docs/note-legibility.md), all runtime/UI-toggleable. The
# SECRET (ANTHROPIC_API_KEY) is NOT here — it lives in env/Config; these are just
# the switch and its knobs.
LEGIBILITY_ENABLED_KEY = "legibility.enabled"      # "true" | "false" (default false = today's behavior)
LEGIBILITY_MODE_KEY = "legibility.mode"            # "auto" | "manual"
LEGIBILITY_THRESHOLD_KEY = "legibility.threshold"  # health score below which auto-rewrite fires
LEGIBILITY_MODEL_KEY = "legibility.model"          # model id for the analysis call

# Defaults when the corresponding row is unset or malformed.
_LEGIBILITY_DEFAULT_MODE = "auto"
# PLACEHOLDER pending the Phase 3 A/B curve (docs/note-legibility.md "Eval / A/B").
# The threshold is the one value still set by evidence, not by feel.
_LEGIBILITY_DEFAULT_THRESHOLD = 60
_LEGIBILITY_DEFAULT_MODEL = "claude-sonnet-4-6"


async def get_setting(pool: asyncpg.Pool, key: str) -> str | None:
    """The stored value for `key`, or None if unset."""
    row = await pool.fetchrow("SELECT value FROM settings WHERE key = $1", key)
    return row["value"] if row else None


async def set_setting(pool: asyncpg.Pool, key: str, value: str) -> None:
    """Upsert `key` = `value` (stamping updated_at)."""
    await pool.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        key,
        value,
    )


async def delete_setting(pool: asyncpg.Pool, key: str) -> bool:
    """Remove `key`. Returns True if a row was deleted (asyncpg's tag is 'DELETE n')."""
    tag = await pool.execute("DELETE FROM settings WHERE key = $1", key)
    return tag.rsplit(" ", 1)[-1] != "0"


async def _read_legibility(pool: asyncpg.Pool) -> tuple[bool, str, int, str]:
    """The raw stored legibility policy with defaults applied →
    (enabled, mode, threshold, model). No key check, no logging — the shared core
    of `_effective_legibility` (ingest) and `legibility_status` (UI). A malformed
    stored value (non-int threshold, unknown mode) falls back to its default rather
    than erroring, so a bad row can't wedge the feature."""
    enabled = (await get_setting(pool, LEGIBILITY_ENABLED_KEY)) == "true"

    mode = await get_setting(pool, LEGIBILITY_MODE_KEY)
    if mode not in ("auto", "manual"):
        mode = _LEGIBILITY_DEFAULT_MODE

    threshold = _LEGIBILITY_DEFAULT_THRESHOLD
    raw = await get_setting(pool, LEGIBILITY_THRESHOLD_KEY)
    if raw is not None:
        try:
            threshold = int(raw)
        except ValueError:
            pass  # malformed -> keep the default, never wedge the feature

    model = (await get_setting(pool, LEGIBILITY_MODEL_KEY)) or _LEGIBILITY_DEFAULT_MODEL
    return enabled, mode, threshold, model


async def _effective_legibility(
    pool: asyncpg.Pool,
) -> tuple[bool, str, int, str]:
    """Resolve the live note-legibility policy at ingest time →
    (enabled, mode, threshold, model). The exact shape/role of
    api._effective_poll_interval, for the same reason: the policy is a set of
    runtime `settings` rows the owner toggles from the UI (no restart), so it can't
    be a boot-time env decision.

    THE config seam: the on/off TOGGLE is a DB value, but the SECRET
    (`Config().anthropic_api_key`) is env-only and `validate()` never gates on it.
    So `enabled but no key` degrades to DISABLED (pass-through), with a warning —
    flipping the toggle on without provisioning the secret can't crash ingest; it
    behaves exactly like today. Mirrors "a bad stored poll value can't wedge
    syncing off." Returns enabled=False whenever the feature should be a no-op.
    """
    enabled, mode, threshold, model = await _read_legibility(pool)
    if enabled and not Config().anthropic_api_key:
        logger.warning(
            "legibility.enabled is true but ANTHROPIC_API_KEY is unset — ingesting "
            "as pass-through (no health/rewrite). Provision the key to enable."
        )
        enabled = False
    return enabled, mode, threshold, model


async def legibility_status(pool: asyncpg.Pool) -> dict:
    """Form-population view of the policy for the UI — the raw stored toggle +
    knobs, whether the secret is present, and whether the feature actually RUNS
    (`active` = enabled AND key). Unlike `_effective_legibility` this never logs (it
    is polled by the integrations status page) and never hides the toggle, so the UI
    can populate the form and warn "you turned it on but there's no key" itself."""
    enabled, mode, threshold, model = await _read_legibility(pool)
    has_key = bool(Config().anthropic_api_key)
    return {
        "enabled": enabled,
        "active": enabled and has_key,
        "mode": mode,
        "threshold": threshold,
        "model": model,
        "has_key": has_key,
    }
