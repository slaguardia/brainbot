"""GET /recall — an embedder outage degrades to lexical-only, never a 502."""

from __future__ import annotations

from brain import store


def test_embedder_down_serves_lexical_hits(client, seed, monkeypatch):
    sid = seed(title="Kayaks", text="Notes on sea kayaking gear.", path="Kayaks")
    seed(title="Bread", text="Sourdough starter feeding schedule.", path="Bread")

    def _down(texts, input_type="document"):
        raise ConnectionError("embedder unreachable")

    monkeypatch.setattr(store, "embed", _down)

    resp = client.get("/recall", params={"q": "kayaking gear"})
    assert resp.status_code == 200
    chunks = resp.json()["chunks"]
    assert [c["id"] for c in chunks] == [sid]  # lexical match only, no semantic noise
