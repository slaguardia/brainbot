"""Runtime settings in Postgres — config the UI manages, not deploy-time env.

A tiny key/value store (the `settings` table lives in db.py's schema). Today it
holds one key: the Notion integration token, set from the PWA's Integrations page
so a deployment can connect Notion without editing NOTION_TOKEN in .env.

Values are secrets — these helpers never log them, and the API layer never
returns a stored token to the client. A DB-stored token takes precedence over the
NOTION_TOKEN env var (see api._active_notion_token); deleting it falls back to env.
"""

from __future__ import annotations

import asyncpg

# The settings keys in use today.
NOTION_TOKEN_KEY = "notion_token"
# Seconds between automatic Notion sync sweeps, set from the UI. A stored value
# overrides BRAIN_POLL_INTERVAL_SECONDS (env); "0" explicitly disables the loop.
POLL_INTERVAL_KEY = "notion_poll_interval"


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
