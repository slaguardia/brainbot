"""DELETE /sources/{id} — un-ingest a page (the inverse of /ingest).

Removing a source must drop its chunks too (ON DELETE CASCADE), be idempotent
(revoking twice is safe), and reject a non-uuid id with a 400 — all through the
full HTTP/JSON path against the real DB.
"""

from __future__ import annotations

import asyncio

DOC_ID = "12121212-1212-4212-8212-121212121212"


def test_delete_removes_source_and_chunks(client, seed, clean_db):
    seed(title="Temp", text="one section\n\nanother", path="A/Temp", source_id=DOC_ID)
    # Pre-condition: the page is in the brain (and produced chunks).
    assert client.get("/doc", params={"id": DOC_ID}).status_code == 200
    assert _chunk_count(clean_db, DOC_ID) > 0

    resp = client.request("DELETE", f"/sources/{DOC_ID}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    # The source is gone and its chunks went with it (cascade).
    assert client.get("/doc", params={"id": DOC_ID}).status_code == 404
    assert _chunk_count(clean_db, DOC_ID) == 0


def test_delete_is_idempotent(client, seed):
    seed(title="Temp", text="body", path="A/Temp", source_id=DOC_ID)
    assert client.request("DELETE", f"/sources/{DOC_ID}").json() == {"deleted": True}
    # Revoking an already-removed page is a no-op, not an error.
    resp = client.request("DELETE", f"/sources/{DOC_ID}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": False}


def test_delete_unknown_id_is_false(client, clean_db):
    resp = client.request("DELETE", "/sources/99999999-9999-4999-8999-999999999999")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": False}


def test_delete_malformed_id_400(client):
    resp = client.request("DELETE", "/sources/not-a-uuid")
    assert resp.status_code == 400
    assert "uuid" in resp.json()["error"]


def _chunk_count(dsn: str, source_id: str) -> int:
    import asyncpg

    async def _run() -> int:
        conn = await asyncpg.connect(dsn)
        try:
            return await conn.fetchval(
                "SELECT count(*) FROM chunks WHERE source_id = $1::uuid", source_id
            )
        finally:
            await conn.close()

    return asyncio.run(_run())
