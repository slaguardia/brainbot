"""GET /changes — the Tier 0 change signal: an opaque global cursor over the
source set, plus whether it differs from a caller's stored `since`.

The cursor must move on every mutation — insert, re-sync, AND delete — while
staying a single cheap aggregate, and it is deliberately COARSER than /doc's
content `version` (a no-op re-sync still moves it). These tests pin all of that
through the full HTTP/JSON path against the real DB.
"""

from __future__ import annotations

A_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_empty_brain_cursor_is_stable(client, clean_db):
    resp = client.get("/changes")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"cursor", "changed"}
    assert isinstance(body["cursor"], str) and body["cursor"]
    # No `since` → nothing to match, so the consumer is told to (initially) fetch.
    assert body["changed"] is True

    cursor = body["cursor"]
    # Stable while nothing changes; a matching `since` settles to not-changed.
    again = client.get("/changes", params={"since": cursor}).json()
    assert again["cursor"] == cursor
    assert again["changed"] is False


def test_insert_moves_cursor(client, seed, clean_db):
    before = client.get("/changes").json()["cursor"]
    seed(title="A", text="body", path="A", source_id=A_ID)

    body = client.get("/changes", params={"since": before}).json()
    assert body["changed"] is True  # cursor advanced past the stored one
    assert body["cursor"] != before
    # Re-reading with the fresh cursor settles back to not-changed.
    assert client.get("/changes", params={"since": body["cursor"]}).json()["changed"] is False


def test_delete_moves_cursor_even_for_non_latest_source(client, seed, clean_db):
    # Seed A first, then B — B carries the later updated_at.
    seed(title="A", text="a", path="A", source_id=A_ID)
    seed(title="B", text="b", path="B", source_id=B_ID)
    before = client.get("/changes").json()["cursor"]

    # Delete the OLDER source: max(updated_at) is unchanged (B is still latest),
    # so only count(*) catches this — exactly why the cursor stamps both. A
    # max(updated_at)-only cursor would silently miss this deletion.
    assert client.request("DELETE", f"/sources/{A_ID}").json() == {"deleted": True}

    after = client.get("/changes", params={"since": before}).json()
    assert after["changed"] is True
    assert after["cursor"] != before


def test_resync_moves_cursor_but_not_doc_version(client, seed, clean_db):
    seed(title="A", text="body", path="A", source_id=A_ID)
    cursor_before = client.get("/changes").json()["cursor"]
    version_before = client.get("/doc", params={"id": A_ID}).json()["version"]

    # Re-ingest identical content: upsert bumps updated_at (a re-sync IS a Tier 0
    # "re-check" event), so the cursor moves — but the per-document content stamp
    # does not. This is the cursor being coarser than `version`, by design: the
    # consumer's relevance gate makes the resulting false positive cheap.
    seed(title="A", text="body", path="A", source_id=A_ID)
    cursor_after = client.get("/changes").json()["cursor"]
    version_after = client.get("/doc", params={"id": A_ID}).json()["version"]

    assert cursor_after != cursor_before
    assert version_after == version_before
