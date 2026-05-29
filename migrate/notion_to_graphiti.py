#!/usr/bin/env python3
"""Migrate Notion content into Graphiti.

Point it at any Notion database id or page id and it produces episodes.
Graphiti's per-write entity extraction handles routing/dedup, so this
script never needs to know the shape of your data.

Default behavior:
- Database mode: one episode per row. Episode name = row's title
  property (or '<db label> row <created date>' fallback). Body = every
  row property flattened as 'Property: value' lines.
- Page mode: split on heading_2 blocks (one episode per H2 section,
  named 'page title - section'); if the page has no H2s, emit one
  whole-page episode. Body = plain-text concatenation of paragraphs,
  headings, lists, quotes.
- Auto mode: probe the Notion object to choose database vs page.

This is a one-shot seed migrator. It does not track what's already
been written and there is no migration log. Re-running posts every
item again — Graphiti's bi-temporal extraction means re-runs link
to existing entities rather than silently fragmenting, but each run
still pays the per-episode extraction cost. Add tracking later if
incremental re-runs become important.

All episodes land in a single global Graphiti group (default 'brain';
override with --group-id). One group = cross-source dedup; the whole
point of the shared brain.

If your Notion data has structure worth preserving differently, fork
this file and edit migrate_database / migrate_page directly. The
extension point IS the source.

Usage:
    python migrate/notion_to_graphiti.py --target <notion-id> --kind auto --dry-run
    python migrate/notion_to_graphiti.py --target <notion-id> --kind database

Required env:
    NOTION_TOKEN              integration token, read access to the target
    BRAIN_URL                 e.g. http://127.0.0.1:8100 (local) or
                              https://brain.api.example.com (VPS)
    BRAIN_BEARER_TOKEN        bearer for Caddy (only on the VPS path)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger("notion_to_graphiti")

KINDS = ("database", "page", "auto")
DEFAULT_GROUP_ID = "brain"


@dataclass
class PlannedEpisode:
    name: str
    body: str
    source_description: str

    def to_arguments(self) -> dict[str, Any]:
        # Informational shape for dry-run logging. The brain's capture() takes
        # only the text; name/source_description are kept for the log.
        return {
            "name": self.name,
            "episode_body": self.body,
            "source_description": self.source_description,
        }


class NotionMigrator:
    def __init__(
        self,
        notion_client,
        graphiti_client,
        dry_run: bool = False,
        since: datetime | None = None,
    ) -> None:
        self.notion = notion_client
        self.graphiti = graphiti_client
        self.dry_run = dry_run
        self.since = since
        self.counts = {"migrated": 0}

    def migrate(self, target_id: str, kind: str = "auto") -> list[PlannedEpisode]:
        if kind == "auto":
            obj = self.notion.get_object(target_id)
            kind = "database" if obj.get("object") == "database" else "page"
            logger.info("auto-detected kind=%s for target=%s", kind, target_id)

        if kind == "database":
            episodes = list(self.migrate_database(target_id))
        elif kind == "page":
            episodes = list(self.migrate_page(target_id))
        else:
            raise ValueError(f"unknown kind: {kind}")

        for ep in episodes:
            self._dispatch(ep)
        return episodes

    def migrate_database(self, database_id: str) -> Iterable[PlannedEpisode]:
        from notion_clients import page_title, prop_text  # type: ignore[import-not-found]

        db = self.notion.fetch_database(database_id)
        db_title = "".join(
            part.get("plain_text", "") for part in (db.get("title") or [])
        ) or database_id

        for row in self.notion.query_database(database_id, since=self.since):
            created = _parse_iso(row.get("created_time")) or datetime.now(timezone.utc)
            title = page_title(row).strip()
            if not title:
                title = f"{db_title} row {created.date().isoformat()}"

            props = row.get("properties", {}) or {}
            body_lines: list[str] = []
            for prop_name, prop_value in props.items():
                value = prop_text(prop_value)
                if value:
                    body_lines.append(f"{prop_name}: {value}")
            body = "\n".join(body_lines) if body_lines else title

            yield PlannedEpisode(
                name=title,
                body=body,
                source_description=f"notion-database:{database_id}",
            )

    def migrate_page(self, page_id: str) -> Iterable[PlannedEpisode]:
        from notion_clients import block_text, page_title  # type: ignore[import-not-found]

        page = self.notion.fetch_page(page_id)
        blocks = self.notion.fetch_page_blocks(page_id)

        title = page_title(page).strip() or f"Notion page {page_id}"

        sections = _split_blocks_by_h2(blocks)
        if not sections:
            text = "\n".join(filter(None, (block_text(b) for b in blocks)))
            if text:
                yield PlannedEpisode(
                    name=title,
                    body=text,
                    source_description=f"notion-page:{page_id}",
                )
            return

        for heading, body_blocks in sections:
            text = "\n".join(filter(None, (block_text(b) for b in body_blocks)))
            if not text:
                continue
            yield PlannedEpisode(
                name=f"{title} - {heading}",
                body=text,
                source_description=f"notion-page:{page_id}",
            )

    def _dispatch(self, episode: PlannedEpisode) -> None:
        if self.dry_run:
            logger.info("[dry-run] %s", json.dumps(episode.to_arguments(), default=str))
            return
        # The brain decomposes + extracts each episode body via capture(). Notion
        # rows/sections are document-shaped, so each becomes one capture call.
        self.graphiti.capture(episode.body)
        self.counts["migrated"] += 1
        logger.info("captured %s", episode.name)


def _split_blocks_by_h2(
    blocks: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group a flat block list into (heading, blocks-under-heading) sections.

    Splits on heading_2. Content above the first heading_2 is dropped to keep
    sections self-contained. Returns [] if the page has no heading_2 blocks.
    """
    from notion_clients import block_text  # type: ignore[import-not-found]

    sections: list[tuple[str, list[dict[str, Any]]]] = []
    current_heading: str | None = None
    current_body: list[dict[str, Any]] = []
    saw_h2 = False

    for block in blocks:
        if block.get("type") == "heading_2":
            saw_h2 = True
            if current_heading is not None:
                sections.append((current_heading, current_body))
            current_heading = block_text(block).strip() or "Section"
            current_body = []
        elif current_heading is not None:
            current_body.append(block)

    if current_heading is not None:
        sections.append((current_heading, current_body))

    return sections if saw_h2 else []


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


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError as e:
        sys.exit(f"--since must be ISO date (YYYY-MM-DD): {e}")


def build_clients(dry_run: bool):
    from notion_clients import NotionClient  # type: ignore[import-not-found]
    from graphiti_clients import BrainClient  # type: ignore[import-not-found]

    notion = NotionClient(token=_require_env("NOTION_TOKEN"))
    if dry_run:
        return notion, _NoOpBrain()

    brain_url = _require_env("BRAIN_URL")
    bearer = os.environ.get("BRAIN_BEARER_TOKEN")
    if brain_url.startswith("https://") and not bearer:
        print(
            "WARNING: BRAIN_BEARER_TOKEN is unset but BRAIN_URL is https — "
            "Caddy will 401. Set BRAIN_BEARER_TOKEN before re-running.",
            file=sys.stderr,
        )
    return notion, BrainClient(base_url=brain_url, bearer=bearer)


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        sys.exit(f"{key} must be set in environment")
    return value


class _NoOpGraphiti:
    def __init__(self, group_id: str) -> None:
        self.group_id = group_id

    def add_memory(self, **_: Any) -> dict[str, Any]:
        return {"message": "dry-run"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Notion database id or page id")
    parser.add_argument("--kind", choices=KINDS, default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", help="ISO date; only migrate items edited on/after")
    parser.add_argument(
        "--group-id",
        default=os.environ.get("GRAPHITI_GROUP_ID", DEFAULT_GROUP_ID),
        help="Graphiti namespace (default: brain, or GRAPHITI_GROUP_ID env)",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(message)s")

    since = parse_since(args.since)
    notion, graphiti = build_clients(dry_run=args.dry_run, group_id=args.group_id)
    migrator = NotionMigrator(
        notion,
        graphiti,
        dry_run=args.dry_run,
        since=since,
    )

    episodes = migrator.migrate(args.target, kind=args.kind)
    logger.info("%s: %d episodes planned (group_id=%s)", args.target, len(episodes), args.group_id)
    logger.info("summary: queued=%d", migrator.counts["migrated"])
    if args.dry_run:
        print(
            f"\nNote: each of these {len(episodes)} episodes triggers Graphiti extraction "
            f"(~$0.0016 with claude-haiku-4-5 + voyage-3-lite, "
            f"~${len(episodes) * 0.0016:.2f} total). "
            "Re-runs re-extract everything — there's no migration log.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
