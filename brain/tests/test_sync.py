"""The periodic-sync staleness rule — the backend twin of the dashboard's isStale.

Pure logic over (page, ingested-map): no DB, no Notion, so this runs anywhere.
The rule decides which already-ingested pages the poll loop re-ingests, so its
edges (never-pulled, no url, no captured time, equal times) are what matter.
"""

from __future__ import annotations

import asyncio

from brain.api import _effective_poll_interval, _is_stale, _new_children
from brain.config import Config


def _page(pid: str, *, url: str | None = "https://notion.so/p", edited: str | None = None) -> dict:
    return {"id": pid, "url": url, "last_edited_time": edited}


def test_not_ingested_is_never_stale():
    # Stale-only sync: a page the human hasn't pulled is not our concern.
    page = _page("a", edited="2026-01-02T00:00:00.000Z")
    assert _is_stale(page, {}) is False


def test_notion_newer_than_capture_is_stale():
    page = _page("a", edited="2026-01-02T00:00:00.000Z")
    assert _is_stale(page, {"a": "2026-01-01T00:00:00+00:00"}) is True


def test_capture_current_is_not_stale():
    # Same instant, different ISO spelling (Notion 'Z' vs Postgres '+00:00').
    page = _page("a", edited="2026-01-01T00:00:00.000Z")
    assert _is_stale(page, {"a": "2026-01-01T00:00:00+00:00"}) is False


def test_no_captured_time_is_stale():
    # Ingested before edit times were recorded → possibly stale → re-pull.
    page = _page("a", edited="2026-01-02T00:00:00.000Z")
    assert _is_stale(page, {"a": None}) is True


def test_no_url_cannot_be_reingested():
    # Databases have no url to /ingest — never flagged.
    page = _page("a", url=None, edited="2026-01-02T00:00:00.000Z")
    assert _is_stale(page, {"a": "2026-01-01T00:00:00+00:00"}) is False


def test_no_edit_time_cannot_be_compared():
    page = _page("a", edited=None)
    assert _is_stale(page, {"a": "2026-01-01T00:00:00+00:00"}) is False


def test_empty_interval_env_falls_back_to_default(monkeypatch):
    # An accidental `BRAIN_POLL_INTERVAL_SECONDS=` in .env must not crash boot
    # with int('') — it falls back to the default like an unset var.
    monkeypatch.setenv("BRAIN_POLL_INTERVAL_SECONDS", "")
    assert Config().poll_interval_seconds == 300


# --- _effective_poll_interval: DB-over-env precedence (the UI's control) ------

class _FakePool:
    """Minimal stand-in for the asyncpg pool get_setting reads: fetchrow returns
    a {'value': ...} row for the stored key, or None when nothing is stored."""

    def __init__(self, stored: str | None):
        self._stored = stored

    async def fetchrow(self, _sql: str, _key: str):
        return {"value": self._stored} if self._stored is not None else None


def test_stored_interval_overrides_env(monkeypatch):
    monkeypatch.setenv("BRAIN_POLL_INTERVAL_SECONDS", "3600")
    seconds, source = asyncio.run(_effective_poll_interval(_FakePool("900")))
    assert (seconds, source) == (900, "db")


def test_stored_zero_disables(monkeypatch):
    # A stored 0 is an explicit "off" that wins over an env that's on.
    monkeypatch.setenv("BRAIN_POLL_INTERVAL_SECONDS", "3600")
    seconds, source = asyncio.run(_effective_poll_interval(_FakePool("0")))
    assert (seconds, source) == (0, "db")


def test_malformed_stored_falls_back_to_env(monkeypatch):
    # A garbage row must not wedge syncing off — env wins instead.
    monkeypatch.setenv("BRAIN_POLL_INTERVAL_SECONDS", "1800")
    seconds, source = asyncio.run(_effective_poll_interval(_FakePool("not-a-number")))
    assert (seconds, source) == (1800, "env")


def test_no_stored_uses_env_default(monkeypatch):
    monkeypatch.delenv("BRAIN_POLL_INTERVAL_SECONDS", raising=False)
    seconds, source = asyncio.run(_effective_poll_interval(_FakePool(None)))
    assert (seconds, source) == (300, "env")


# --- _new_children: auto-discover pages under already-pulled content -----------
#
# Pure over the world list (list_pages items) + the ingested-id map, like _is_stale.
# A "node" is a list_pages item: id, kind, parent_id, url (databases have no url).

def _node(pid: str, *, kind: str = "page", parent: str | None = None,
          url: str = "https://notion.so/p") -> dict:
    return {"id": pid, "kind": kind, "parent_id": parent, "url": url}


def test_child_of_pulled_page_is_discovered():
    pages = [_node("root"), _node("kid", parent="root")]
    assert [p["id"] for p in _new_children(pages, {"root": None})] == ["kid"]


def test_new_row_of_pulled_database_is_discovered():
    # We have row r1 (parent = database db); r2 is a new row under the same db.
    # The db node itself is never pulled — having a row seeds discovery of new rows.
    pages = [
        _node("db", kind="database", url=""),
        _node("r1", parent="db"),
        _node("r2", parent="db"),
    ]
    assert [p["id"] for p in _new_children(pages, {"r1": None})] == ["r2"]


def test_already_pulled_page_is_not_rediscovered():
    pages = [_node("root"), _node("kid", parent="root")]
    assert _new_children(pages, {"root": None, "kid": None}) == []


def test_page_under_unpulled_parent_is_ignored():
    # `other` is a workspace-root page we never pulled — not under pulled content.
    pages = [_node("root"), _node("kid", parent="root"), _node("other")]
    assert [p["id"] for p in _new_children(pages, {"root": None})] == ["kid"]


def test_nested_database_rows_discovered_but_database_not_ingested():
    # A database nested under a pulled page: its rows are new children, but the
    # database node itself is never returned (no url to /ingest).
    pages = [
        _node("root"),
        _node("db", kind="database", parent="root", url=""),
        _node("row", parent="db"),
    ]
    assert [p["id"] for p in _new_children(pages, {"root": None})] == ["row"]


def test_deep_descendant_caught_in_one_pass():
    pages = [
        _node("root"),
        _node("a", parent="root"),
        _node("b", parent="a"),
        _node("c", parent="b"),
    ]
    assert sorted(p["id"] for p in _new_children(pages, {"root": None})) == ["a", "b", "c"]


def test_nothing_pulled_discovers_nothing():
    pages = [_node("root"), _node("kid", parent="root")]
    assert _new_children(pages, {}) == []


def test_reached_page_without_url_is_skipped():
    # A reachable child that has no url can't be /ingested — leave it out.
    pages = [_node("root"), _node("kid", parent="root", url="")]
    assert _new_children(pages, {"root": None}) == []

