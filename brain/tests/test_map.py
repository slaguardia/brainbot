"""GET /map — the consumer discovery surface: stable ids, display titles/paths,
parent links, version stamps. No chunk contents, no sync metadata."""

from __future__ import annotations

from brain.notion import _parent_id

PARENT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CHILD = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_consumer_shape_and_parent_resolution(client, seed):
    seed(title="Hub", text="hub body", path="Hub", source_id=PARENT)
    seed(title="Leaf", text="leaf body", path="Hub/Leaf", source_id=CHILD, parent_id=PARENT)

    resp = client.get("/map")
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert [s["id"] for s in sources] == [PARENT, CHILD]  # ordered by path

    # Exactly the contract keys — no chunk contents, no kind/timestamps/counters.
    # `health` joined the contract with the note-legibility layer; it is null for
    # un-analyzed sources (these were seeded with legibility off).
    for s in sources:
        assert set(s) == {"id", "title", "path", "parent_id", "version", "health"}
        assert s["health"] is None

    hub, leaf = sources
    assert hub["parent_id"] is None
    assert leaf["parent_id"] == PARENT  # parent is synced -> resolved to its id

    # `version` means the same thing on /map and /doc — same stamp per id.
    for s in sources:
        assert s["version"] == client.get("/doc", params={"id": s["id"]}).json()["version"]


def test_unsynced_parent_resolves_to_null(client, seed):
    # The Notion parent exists upstream but was never synced: its id must not
    # leak — the row appears as a root (parent_id null is overloaded by design).
    seed(
        title="Orphan",
        text="body",
        path="Orphan",
        source_id=CHILD,
        parent_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    )
    [row] = client.get("/map").json()["sources"]
    assert row["parent_id"] is None


def test_scope_filters_subtree(client, seed):
    seed(title="In", text="x", path="Hub/In", source_id=PARENT)
    seed(title="Out", text="y", path="Other/Out", source_id=CHILD)
    rows = client.get("/map", params={"scope": "Hub"}).json()["sources"]
    assert [r["path"] for r in rows] == ["Hub/In"]


def test_scoped_map_resolves_out_of_scope_parent(client, seed):
    """parent_id resolution is against ALL synced sources, not the scoped
    response set: a scoped /map may name a parent that isn't in this response
    (it's a linkage hint, not an authoritative tree — pinned here on purpose)."""
    seed(title="Hub", text="h", path="Other/Hub", source_id=PARENT)
    seed(title="Leaf", text="l", path="Hub/Leaf", source_id=CHILD, parent_id=PARENT)
    rows = client.get("/map", params={"scope": "Hub"}).json()["sources"]
    assert [r["id"] for r in rows] == [CHILD]
    assert rows[0]["parent_id"] == PARENT  # synced, just outside this scope


def test_recall_chunks_carry_the_doc_id(client, seed):
    """The recall->doc bridge: a hit must name its owning document's stable id,
    or a consumer wanting the whole page is forced into forbidden title/path
    matching."""
    seed(title="Zebra notes", text="the zebra gallops at dawn", path="Zoo/Zebra", source_id=PARENT)

    resp = client.get("/recall", params={"q": "zebra gallops"})
    assert resp.status_code == 200
    chunks = resp.json()["chunks"]
    assert chunks, "lexical arm should match the seeded text"
    assert set(chunks[0]) == {"id", "heading", "text", "score", "path"}
    assert chunks[0]["id"] == PARENT
    # The id is the /doc key — the escalation round-trips.
    assert client.get("/doc", params={"id": chunks[0]["id"]}).status_code == 200


# ---- notion parent extraction (pure unit — no DB) -----------------------------

def test_parent_id_extraction():
    page_parent = {"parent": {"type": "page_id", "page_id": PARENT}}
    db_parent = {"parent": {"type": "database_id", "database_id": CHILD}}
    workspace = {"parent": {"type": "workspace", "workspace": True}}
    block = {"parent": {"type": "block_id", "block_id": "ignored"}}
    assert _parent_id(page_parent) == PARENT
    assert _parent_id(db_parent) == CHILD
    assert _parent_id(workspace) is None
    assert _parent_id(block) is None
    assert _parent_id({}) is None
