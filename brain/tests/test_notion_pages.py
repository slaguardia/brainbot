"""GET /notion/pages — the discovery universe: every integration-visible page
flagged `ingested`, with `ingested_last_edited` (the origin edit time the brain
captured at ingest) on ingested pages so a consumer can compare it to Notion's
current `last_edited_time` and spot stale copies. Notion itself is faked at the
api-module boundary; the sources table underneath is real."""

from __future__ import annotations

from brain import api

INGESTED = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRE_STAMP = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NOT_PULLED = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _page(pid: str, title: str) -> dict:
    return {
        "id": pid,
        "kind": "page",
        "title": title,
        "parent_id": None,
        "last_edited_time": "2026-06-05T12:00:00.000Z",
        "url": f"https://notion.so/{pid.replace('-', '')}",
    }


def test_ingested_pages_carry_the_captured_edit_time(client, seed, monkeypatch):
    seed(
        title="Current",
        text="x",
        path="Current",
        source_id=INGESTED,
        last_edited="2026-06-01T00:00:00.000Z",
    )
    # Ingested before the edit time was recorded: must surface as None (the
    # consumer treats "unknown" as possibly stale), not vanish from the shape.
    seed(title="Old", text="y", path="Old", source_id=PRE_STAMP)

    pages = [_page(INGESTED, "Current"), _page(PRE_STAMP, "Old"), _page(NOT_PULLED, "New")]
    # list_pages now takes the resolved Notion token (env/DB) as its one arg.
    monkeypatch.setattr(api, "list_pages", lambda token=None: [dict(p) for p in pages])

    resp = client.get("/notion/pages")
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()["pages"]}

    assert by_id[INGESTED]["ingested"] is True
    # ISO 8601 with an explicit offset — directly comparable, as an instant,
    # against Notion's `last_edited_time`.
    assert by_id[INGESTED]["ingested_last_edited"] == "2026-06-01T00:00:00+00:00"

    assert by_id[PRE_STAMP]["ingested"] is True
    assert by_id[PRE_STAMP]["ingested_last_edited"] is None

    # Not-ingested pages don't grow the key — `ingested` already says it all.
    assert by_id[NOT_PULLED]["ingested"] is False
    assert "ingested_last_edited" not in by_id[NOT_PULLED]
