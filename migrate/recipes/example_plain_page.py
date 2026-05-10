"""Example recipe: collapse a Notion page into a single episode.

Demonstrates the recipe contract. Useful as a starting point — copy and
modify in your own fork. Does NOT split on H2; produces exactly one
episode per page regardless of structure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from notion_to_graphiti import PlannedEpisode, RecipeContext  # type: ignore[import-not-found]
from notion_clients import block_text, page_title  # type: ignore[import-not-found]


def as_one_episode(
    item: dict[str, Any], context: RecipeContext
) -> PlannedEpisode | None:
    if context.kind != "page":
        return None

    title = page_title(item).strip() or f"Notion page {context.target_id}"
    blocks = context.notion_client.fetch_page_blocks(context.target_id)
    body = "\n".join(filter(None, (block_text(b) for b in blocks))) or title

    created = item.get("created_time")
    last_edited = item.get("last_edited_time")
    ref_time = _parse_iso(created) or datetime.now(timezone.utc)

    return PlannedEpisode(
        name=title,
        body=body,
        source_description=f"notion-page:{context.target_id} (recipe:plain)",
        reference_time=ref_time,
        entity_hints={},
        notion_page_id=item.get("id", ""),
        notion_last_edited=_parse_iso(last_edited),
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
