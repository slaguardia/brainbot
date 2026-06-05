"""GET /doc — the consumer pin-by-id / cache-by-version primitive.

The headline guarantee: `text` is the stored document VERBATIM, byte for byte,
through the full asyncpg + Postgres + JSON path. A consumer pins a page id
(e.g. a frozen email-template paragraph) and must get exactly the stored bytes
back, every time. The companion guarantee is the `version` stamp: it moves iff
the served {title, text} change — never on a mere re-sync, never on a path
(display ancestry) change.
"""

from __future__ import annotations

import asyncio

import pytest

# The frozen-template stand-in: every byte class that could plausibly be
# mangled between ingest and the JSON layer — CRLF, trailing/leading spaces,
# tabs, smart quotes, backslashes, emoji, combining vs precomposed accents, a
# C0 control char, blank lines, and a trailing newline.
FROZEN = (
    "  leading spaces preserved\n"
    "trailing spaces preserved   \n"
    "a CRLF line ends here\r\n"
    "tab\there; em-dash —, “smart quotes”, backslash \\ and \"quotes\"\n"
    "emoji \U0001f680; combining é vs precomposed é\n"
    "C0 control \x1f (unit separator) survives\n"
    "\n"
    "last line, then a trailing newline\n"
)

DOC_ID = "11111111-1111-4111-8111-111111111111"


def test_roundtrip_byte_exact(client, seed):
    seed(title="Frozen template", text=FROZEN, path="Bank/Frozen template", source_id=DOC_ID)

    resp = client.get("/doc", params={"id": DOC_ID})
    assert resp.status_code == 200
    data = resp.json()
    # THE contract: the text comes back byte-identical to what was stored.
    assert data["text"] == FROZEN
    assert data["id"] == DOC_ID
    assert data["title"] == "Frozen template"
    assert data["path"] == "Bank/Frozen template"
    # The version stamp is an md5 hex digest.
    assert isinstance(data["version"], str) and len(data["version"]) == 32
    int(data["version"], 16)
    # Exactly the contract keys — nothing internal leaks.
    assert set(data) == {"id", "title", "path", "version", "text"}


def test_accepts_undashed_id(client, seed):
    seed(title="T", text="body", path="A/T", source_id=DOC_ID)

    resp = client.get("/doc", params={"id": DOC_ID.replace("-", "")})
    assert resp.status_code == 200
    # Canonical dashed form in the response, whatever form came in.
    assert resp.json()["id"] == DOC_ID


def test_unknown_id_404(client):
    resp = client.get("/doc", params={"id": "99999999-9999-4999-8999-999999999999"})
    assert resp.status_code == 404
    # Assert on the body too — proves the HANDLER 404'd, not the router.
    assert "no document" in resp.json()["error"]


def test_malformed_or_missing_id_400(client):
    for params in ({"id": "not-a-uuid"}, {"id": "  "}, {}):
        resp = client.get("/doc", params=params)
        assert resp.status_code == 400
        assert "id" in resp.json()["error"]


def test_version_semantics(client, seed):
    """The stamp moves iff served content changes:
    unchanged re-sync -> stable; text edit -> moves; title-only edit -> moves;
    path-only change (ancestor rename) -> stable, path served fresh."""
    seed(title="T", text="body v1", path="A/T", source_id=DOC_ID)
    v1 = client.get("/doc", params={"id": DOC_ID}).json()["version"]

    # Unchanged re-sync: the int version column bumps, the consumer stamp must not.
    seed(title="T", text="body v1", path="A/T", source_id=DOC_ID)
    assert client.get("/doc", params={"id": DOC_ID}).json()["version"] == v1

    # Content edit: stamp moves.
    seed(title="T", text="body v2", path="A/T", source_id=DOC_ID)
    v2 = client.get("/doc", params={"id": DOC_ID}).json()["version"]
    assert v2 != v1

    # Title-only edit: the served representation changed, so the stamp moves.
    seed(title="T renamed", text="body v2", path="A/T renamed", source_id=DOC_ID)
    v3 = client.get("/doc", params={"id": DOC_ID}).json()["version"]
    assert v3 != v2

    # Path-only change (an ANCESTOR rename: same title, same text, new path):
    # display ancestry is not version-covered — stamp stays, path serves fresh.
    seed(title="T renamed", text="body v2", path="B/T renamed", source_id=DOC_ID)
    data = client.get("/doc", params={"id": DOC_ID}).json()
    assert data["version"] == v3
    assert data["path"] == "B/T renamed"


def test_version_title_text_boundary(client, seed):
    """Regression for the hash construction: ('A', '\\x1fB') and ('A\\x1f', 'B')
    are different documents and must not share a stamp — a plain-separator hash
    collides here; the length-prefixed one must not."""
    a = "22222222-2222-4222-8222-222222222222"
    b = "33333333-3333-4333-8333-333333333333"
    seed(title="A", text="\x1fB", path="X/A", source_id=a)
    seed(title="A\x1f", text="B", path="X/B", source_id=b)
    va = client.get("/doc", params={"id": a}).json()["version"]
    vb = client.get("/doc", params={"id": b}).json()["version"]
    assert va != vb


def test_null_title_serves_empty_and_matches_empty_title_version(client, clean_db):
    """A NULL title (pre-upsert-era rows / direct inserts) serves as "" and
    stamps identically to an empty title — the served representations are
    identical, so the stamp collision is correct, not a defect."""
    import asyncpg

    null_id = "44444444-4444-4444-8444-444444444444"
    empty_id = "55555555-5555-4555-8555-555555555555"

    async def _insert() -> None:
        conn = await asyncpg.connect(clean_db)
        try:
            await conn.execute(
                """
                INSERT INTO sources (id, kind, title, raw_text, path)
                VALUES ($1::uuid, 'notion_page', NULL, 'same body', 'N/a'),
                       ($2::uuid, 'notion_page', '',   'same body', 'N/b')
                """,
                null_id,
                empty_id,
            )
        finally:
            await conn.close()

    asyncio.run(_insert())

    null_doc = client.get("/doc", params={"id": null_id}).json()
    empty_doc = client.get("/doc", params={"id": empty_id}).json()
    assert null_doc["title"] == ""  # never JSON null
    assert null_doc["version"] == empty_doc["version"]


def test_whitespace_title_round_trips_verbatim(client, seed):
    """A whitespace-only title is its own case (truthy, length 3): served
    verbatim — never stripped — and stamped distinctly from an empty title."""
    ws_id = "77777777-7777-4777-8777-777777777777"
    empty_id = "88888888-8888-4888-8888-888888888888"
    seed(title="   ", text="same body", path="W/a", source_id=ws_id)
    seed(title="", text="same body", path="W/b", source_id=empty_id)

    ws_doc = client.get("/doc", params={"id": ws_id}).json()
    assert ws_doc["title"] == "   "
    assert ws_doc["version"] != client.get("/doc", params={"id": empty_id}).json()["version"]


def test_mcp_doc_tool_mirrors_http(client, seed, mcp_call):
    """The MCP face duplicates the HTTP route's id handling — pin the parity:
    undashed in -> dashed-canonical out, same contract keys, ValueError on a
    malformed or unknown id."""
    import pytest as _pytest

    from brain.api import doc_tool

    seed(title="T", text="body", path="A/T", source_id=DOC_ID)

    via_mcp = mcp_call(doc_tool, id=DOC_ID.replace("-", ""))
    via_http = client.get("/doc", params={"id": DOC_ID}).json()
    assert via_mcp == via_http

    with _pytest.raises(ValueError, match="must be a document uuid"):
        mcp_call(doc_tool, id="not-a-uuid")
    with _pytest.raises(ValueError, match="no document"):
        mcp_call(doc_tool, id="99999999-9999-4999-8999-999999999999")


def test_lone_surrogate_is_not_storable(seed):
    """The storable-text boundary /doc's byte-exactness rests on: a lone
    surrogate cannot be stored (asyncpg refuses to UTF-8-encode it), so it can
    never reach the JSON layer — where it would 500. If this ever starts
    passing, ingest sanitization needs a surrogate strip alongside its NUL
    strip before /doc's guarantee breaks."""
    import asyncpg

    with pytest.raises(asyncpg.DataError, match="surrogates not allowed"):
        seed(
            title="bad",
            text="lone surrogate \ud800 here",
            path="X/bad",
            source_id="66666666-6666-4666-8666-666666666666",
        )
