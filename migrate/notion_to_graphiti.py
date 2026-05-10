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

If your Notion data has structure worth preserving differently, fork
this file and edit migrate_database / migrate_page directly. The
extension point IS the source.

Usage:
    python migrate/notion_to_graphiti.py --target <notion-id> --kind auto --dry-run
    python migrate/notion_to_graphiti.py --target <notion-id> --kind database

Required env:
    NOTION_TOKEN              integration token, read access to the target
    BRAIN_URL                 e.g. https://brain.example.com
    BRAIN_BEARER_TOKEN        bearer for Caddy
    PERSONAL_DATABASE_URL     Postgres URL for brain.migration_log (idempotency)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger("notion_to_graphiti")

KINDS = ("database", "page", "auto")


@dataclass
class PlannedEpisode:
    name: str
    body: str
    source_description: str
    reference_time: datetime
    entity_hints: dict[str, Any] = field(default_factory=dict)
    notion_page_id: str = ""
    notion_last_edited: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "body": self.body,
            "source_description": self.source_description,
            "reference_time": self.reference_time.isoformat(),
            "entity_hints": self.entity_hints,
        }


class MigrationLog:
    """Tracks which Notion items have been migrated and at what edit time.

    Backed by Postgres table brain.migration_log (PK: notion_page_id).
    Use status() to decide whether an item should be migrated, skipped,
    or re-migrated. record() persists the result of a successful add_episode.
    """

    SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "sql", "001_migration_log.sql")

    def __init__(self, conn) -> None:
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with open(self.SCHEMA_FILE) as f:
            ddl = f.read()
        with self.conn.cursor() as cur:
            cur.execute(ddl)
        self.conn.commit()

    def status(self, page_id: str, last_edited: datetime) -> str:
        """Return 'new', 'changed', or 'unchanged'."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT notion_last_edited FROM brain.migration_log "
                "WHERE notion_page_id=%s",
                (page_id,),
            )
            row = cur.fetchone()
        if row is None:
            return "new"
        stored = row[0]
        return "changed" if last_edited > stored else "unchanged"

    def record(
        self,
        target_id: str,
        page_id: str,
        last_edited: datetime,
        episode_id: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO brain.migration_log
                    (notion_page_id, target_id, notion_last_edited, graphiti_episode_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (notion_page_id)
                DO UPDATE SET
                    target_id = EXCLUDED.target_id,
                    notion_last_edited = EXCLUDED.notion_last_edited,
                    graphiti_episode_id = EXCLUDED.graphiti_episode_id,
                    migrated_at = now()
                """,
                (page_id, target_id, last_edited, episode_id),
            )
        self.conn.commit()


class NotionMigrator:
    def __init__(
        self,
        notion_client,
        graphiti_client,
        log: "MigrationLog | None" = None,
        dry_run: bool = False,
        since: datetime | None = None,
    ) -> None:
        self.notion = notion_client
        self.graphiti = graphiti_client
        self.log = log
        self.dry_run = dry_run
        self.since = since
        self.counts = {"migrated": 0, "skipped": 0, "remigrated": 0}

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
            self._dispatch(target_id, ep)
        return episodes

    def migrate_database(self, database_id: str) -> Iterable[PlannedEpisode]:
        from notion_clients import page_title, prop_text  # type: ignore[import-not-found]

        db = self.notion.fetch_database(database_id)
        db_title = "".join(
            part.get("plain_text", "") for part in (db.get("title") or [])
        ) or database_id

        for row in self.notion.query_database(database_id, since=self.since):
            row_id = row.get("id", "")
            created = _parse_iso(row.get("created_time")) or datetime.now(timezone.utc)
            last_edited = _parse_iso(row.get("last_edited_time"))

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
                reference_time=created,
                entity_hints={},
                notion_page_id=row_id,
                notion_last_edited=last_edited,
            )

    def migrate_page(self, page_id: str) -> Iterable[PlannedEpisode]:
        from notion_clients import block_text, page_title  # type: ignore[import-not-found]

        page = self.notion.fetch_page(page_id)
        blocks = self.notion.fetch_page_blocks(page_id)

        title = page_title(page).strip() or f"Notion page {page_id}"
        last_edited = _parse_iso(page.get("last_edited_time"))
        ref_time = _parse_iso(page.get("created_time")) or datetime.now(timezone.utc)

        sections = _split_blocks_by_h2(blocks)
        if not sections:
            text = "\n".join(filter(None, (block_text(b) for b in blocks)))
            if text:
                yield PlannedEpisode(
                    name=title,
                    body=text,
                    source_description=f"notion-page:{page_id}",
                    reference_time=ref_time,
                    entity_hints={},
                    notion_page_id=page_id,
                    notion_last_edited=last_edited,
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
                reference_time=ref_time,
                entity_hints={"section": heading},
                notion_page_id=page_id,
                notion_last_edited=last_edited,
            )

    def _dispatch(self, target_id: str, episode: PlannedEpisode) -> None:
        if self.dry_run:
            logger.info("[dry-run] %s", json.dumps(episode.to_payload(), default=str))
            return

        page_id = episode.notion_page_id
        last_edited = episode.notion_last_edited
        if self.log is not None and page_id and last_edited is not None:
            state = self.log.status(page_id, last_edited)
            if state == "unchanged":
                self.counts["skipped"] += 1
                logger.info("skip %s (%s): unchanged since last migration", episode.name, page_id)
                return
            episode_id = self.graphiti.add_episode(episode.to_payload())
            self.log.record(target_id, page_id, last_edited, episode_id)
            if state == "changed":
                self.counts["remigrated"] += 1
                logger.info("re-migrated %s (%s) -> %s", episode.name, page_id, episode_id)
            else:
                self.counts["migrated"] += 1
                logger.info("migrated %s (%s) -> %s", episode.name, page_id, episode_id)
        else:
            episode_id = self.graphiti.add_episode(episode.to_payload())
            self.counts["migrated"] += 1
            logger.info("posted %s -> %s", episode.name, episode_id)


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
    from graphiti_clients import GraphitiClient  # type: ignore[import-not-found]

    notion = NotionClient(token=_require_env("NOTION_TOKEN"))
    if dry_run:
        return notion, _NoOpGraphiti(), None

    graphiti = GraphitiClient(
        base_url=_require_env("BRAIN_URL"),
        bearer=_require_env("BRAIN_BEARER_TOKEN"),
    )
    import psycopg2  # type: ignore[import-not-found]

    conn = psycopg2.connect(_require_env("PERSONAL_DATABASE_URL"))
    return notion, graphiti, MigrationLog(conn)


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        sys.exit(f"{key} must be set in environment")
    return value


class _NoOpGraphiti:
    def add_episode(self, payload: dict[str, Any]) -> str:
        return "dry-run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Notion database id or page id")
    parser.add_argument("--kind", choices=KINDS, default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", help="ISO date; only migrate items edited on/after")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(message)s")

    since = parse_since(args.since)
    notion, graphiti, log = build_clients(dry_run=args.dry_run)
    migrator = NotionMigrator(
        notion,
        graphiti,
        log=log,
        dry_run=args.dry_run,
        since=since,
    )

    episodes = migrator.migrate(args.target, kind=args.kind)
    logger.info("%s: %d episodes planned", args.target, len(episodes))
    logger.info(
        "summary: migrated=%d remigrated=%d skipped=%d",
        migrator.counts["migrated"],
        migrator.counts["remigrated"],
        migrator.counts["skipped"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
