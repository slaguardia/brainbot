"""Thin Notion REST wrapper used by notion_to_graphiti.

Only the slice the migrator needs: paginated database query and
page+blocks fetch, plus property and block flatteners. No third-party
SDK dependency, just `requests`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import requests

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"


class NotionClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def get_object(self, object_id: str) -> dict[str, Any]:
        """Probe whether `object_id` is a page or a database.

        Tries page first; on 404 falls back to database. Used for --kind=auto.
        """
        page_resp = self.session.get(f"{BASE}/pages/{object_id}", timeout=15)
        if page_resp.ok:
            return page_resp.json()
        db_resp = self.session.get(f"{BASE}/databases/{object_id}", timeout=15)
        db_resp.raise_for_status()
        return db_resp.json()

    def query_database(
        self, database_id: str, since: datetime | None = None
    ) -> Iterable[dict[str, Any]]:
        cursor: str | None = None
        body: dict[str, Any] = {"page_size": 100}
        if since is not None:
            body["filter"] = {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": since.isoformat()},
            }
        while True:
            payload = dict(body)
            if cursor:
                payload["start_cursor"] = cursor
            r = self.session.post(f"{BASE}/databases/{database_id}/query", json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            for row in data.get("results", []):
                yield row
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")

    def fetch_page(self, page_id: str) -> dict[str, Any]:
        r = self.session.get(f"{BASE}/pages/{page_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    def fetch_database(self, database_id: str) -> dict[str, Any]:
        r = self.session.get(f"{BASE}/databases/{database_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    def fetch_page_blocks(self, page_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            r = self.session.get(
                f"{BASE}/blocks/{page_id}/children", params=params, timeout=15
            )
            r.raise_for_status()
            data = r.json()
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                return blocks
            cursor = data.get("next_cursor")


def prop_text(prop: dict[str, Any] | None) -> str:
    """Best-effort flatten of a Notion property to a plain string."""
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title":
        return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    if t == "rich_text":
        return "".join(part.get("plain_text", "") for part in prop.get("rich_text", []))
    if t == "select":
        sel = prop.get("select") or {}
        return sel.get("name", "")
    if t == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    if t == "status":
        st = prop.get("status") or {}
        return st.get("name", "")
    if t == "date":
        d = prop.get("date") or {}
        return d.get("start", "") or ""
    if t == "url":
        return prop.get("url") or ""
    if t == "email":
        return prop.get("email") or ""
    if t == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if t == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    return ""


def page_title(page: dict[str, Any]) -> str:
    """Find the title of a Notion page (database row or standalone page)."""
    props = page.get("properties", {}) or {}
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return ""


def block_text(block: dict[str, Any]) -> str:
    """Extract plain text from a Notion block (paragraphs, headings, lists, quotes)."""
    bt = block.get("type")
    if not bt:
        return ""
    payload = block.get(bt) or {}
    rich = payload.get("rich_text") or []
    return "".join(part.get("plain_text", "") for part in rich)
