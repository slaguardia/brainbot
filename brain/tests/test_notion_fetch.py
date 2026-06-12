"""fetch_page — folding a Notion database ROW's properties into ingest content.

A database row keeps its content in PROPERTIES (e.g. a "Body" rich_text column),
not page-body blocks, so the row's block tree is empty and only the title would be
captured. fetch_page folds the row's rich_text properties in as `## <Property>`
sections — but ONLY for database rows; regular pages keep page-body-only ingest.
Notion's HTTP layer is mocked; these are pure-ish unit tests, no DB, no network.
"""

from __future__ import annotations

from brain import notion

URL = "https://notion.so/3767973a545381a19725fa615b3af92a"

DB_ROW = {
    "id": "3767973a-5453-81a1-9725-fa615b3af92a",
    "parent": {"type": "database_id", "database_id": "e45ed457-5a59-4d65-97f8-45602b329981"},
    "last_edited_time": "2026-06-05T12:00:00.000Z",
    "properties": {
        # Notion returns properties in its own order; sections follow that order.
        "Why it works": {"type": "rich_text", "rich_text": [{"plain_text": "usage note"}]},
        "Body": {"type": "rich_text", "rich_text": [{"plain_text": "the real content"}]},
        "Kind": {"type": "select", "select": {"name": "Either"}},  # metadata, not content
        "Name": {"type": "title", "title": [{"plain_text": "My Template"}]},  # the title
    },
}


def test_property_text_folds_rich_text_only():
    out = notion._property_text(DB_ROW)
    assert out == "## Why it works\nusage note\n\n## Body\nthe real content"
    # title-typed and select-typed properties are not content.
    assert "My Template" not in out
    assert "Either" not in out


def test_property_text_skips_empty_rich_text():
    page = {"properties": {"Body": {"type": "rich_text", "rich_text": []}}}
    assert notion._property_text(page) == ""


def test_fetch_page_folds_db_row_properties(monkeypatch):
    # _get returns the row object; the row's block tree is empty (typical).
    monkeypatch.setattr(notion, "_get", lambda path, cfg, **kw: DB_ROW)
    monkeypatch.setattr(notion, "_page_text", lambda pid, cfg: "")
    monkeypatch.setattr(notion, "_ancestor_titles", lambda page, cfg: [])
    page = notion.fetch_page(URL, token="x")
    assert page["title"] == "My Template"
    assert "## Body\nthe real content" in page["text"]
    assert "## Why it works\nusage note" in page["text"]
    assert "Either" not in page["text"]  # select metadata not folded as content
    assert page["parent_id"] == "e45ed457-5a59-4d65-97f8-45602b329981"


def test_fetch_page_db_row_keeps_body_after_properties(monkeypatch):
    # A row that DOES have body blocks: properties lead, body follows.
    monkeypatch.setattr(notion, "_get", lambda path, cfg, **kw: DB_ROW)
    monkeypatch.setattr(notion, "_page_text", lambda pid, cfg: "trailing body note")
    monkeypatch.setattr(notion, "_ancestor_titles", lambda page, cfg: [])
    page = notion.fetch_page(URL, token="x")
    assert page["text"].endswith("trailing body note")
    assert page["text"].index("## Body") < page["text"].index("trailing body note")


def test_fetch_page_db_row_path_walks_through_database(monkeypatch):
    # A row's path must bubble up through its database (and the database's own
    # parent page) instead of stranding the row at the tree root. The row's
    # parent is a database_id; the database's parent is a page_id.
    db = {
        "id": "e45ed457-5a59-4d65-97f8-45602b329981",
        "parent": {"type": "page_id", "page_id": "11111111-1111-4111-8111-111111111111"},
        "title": [{"plain_text": "Writing Bank"}],
        "properties": {},  # a database's `properties` is its SCHEMA, not a title prop
    }
    parent_page = {
        "id": "11111111-1111-4111-8111-111111111111",
        "parent": {"type": "workspace", "workspace": True},
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Notebooks"}]}},
    }
    by_path = {
        "/pages/3767973a-5453-81a1-9725-fa615b3af92a": DB_ROW,
        "/databases/e45ed457-5a59-4d65-97f8-45602b329981": db,
        "/pages/11111111-1111-4111-8111-111111111111": parent_page,
    }
    monkeypatch.setattr(notion, "_get", lambda path, cfg, **kw: by_path[path])
    monkeypatch.setattr(notion, "_page_text", lambda pid, cfg: "")
    page = notion.fetch_page(URL, token="x")
    assert page["path"] == "Notebooks/Writing Bank/My Template"


def test_fetch_page_regular_page_does_not_fold_properties(monkeypatch):
    regular = {
        "id": "3767973a-5453-81a1-9725-fa615b3af92a",
        "parent": {"type": "page_id", "page_id": "11111111-1111-4111-8111-111111111111"},
        "last_edited_time": None,
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Reg"}]},
            "Body": {"type": "rich_text", "rich_text": [{"plain_text": "in a property — ignore"}]},
        },
    }
    monkeypatch.setattr(notion, "_get", lambda path, cfg, **kw: regular)
    monkeypatch.setattr(notion, "_page_text", lambda pid, cfg: "real body content")
    monkeypatch.setattr(notion, "_ancestor_titles", lambda page, cfg: [])
    page = notion.fetch_page(URL, token="x")
    # A regular page's content is its body blocks; properties are not folded.
    assert page["text"] == "real body content"
    assert "in a property" not in page["text"]
