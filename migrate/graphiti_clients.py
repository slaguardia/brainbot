"""Brain client — thin typed HTTP interface to the brain service.

The canonical Python client for consumer apps. The brain exposes three
operations over plain HTTP/JSON — capture, recall, profile — plus a health
probe. No MCP and no session handshake here: that face exists too, but it's
for Claude Code / LLM harnesses. Typed consumers use these HTTP routes.

Stdlib + requests only, so an external consumer can copy this single file.
(The filename is historical — it predates the brain-service rename; the class
is `BrainClient`.)

  - capture(text, group_id=None)            -> dict   POST /capture  (rewrite+extract; slow)
  - recall(query, limit=20, group_id=None)  -> list   GET  /recall   (scored facts, best first)
  - profile(group_id=None)                  -> list   GET  /profile  (episode bodies)
  - health()                                -> dict   GET  /health

`group_id` overrides the target graph (defaults to the brain's configured one) —
used for test isolation, e.g. a `smoketest` graph. See docs/consumer-api.md for
the full per-operation spec.
"""

from __future__ import annotations

from typing import Any

import requests


class BrainClient:
    def __init__(self, base_url: str, bearer: str | None = None, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        if bearer:
            self.session.headers["Authorization"] = f"Bearer {bearer}"

    # ---- transport -----------------------------------------------------------

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        r = self.session.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kw)
        try:
            data: Any = r.json()
        except ValueError:
            data = None
        if not r.ok:
            detail = data.get("error") if isinstance(data, dict) else (r.text or "")
            raise RuntimeError(f"brain {method} {path} -> HTTP {r.status_code}: {detail}")
        return data

    # ---- operations ----------------------------------------------------------

    def capture(self, text: str, group_id: str | None = None) -> dict:
        """Write a thought/note. The brain rewrites it into faithful prose and
        extracts facts server-side, so this returns after the pipeline finishes
        (seconds). Returns {mode, episodes, topic}. Pass group_id to target a
        non-default graph (e.g. test isolation)."""
        body: dict[str, Any] = {"text": text}
        if group_id:
            body["group_id"] = group_id
        return self._request("POST", "/capture", json=body)

    def recall(self, query: str, limit: int = 20, group_id: str | None = None) -> list[dict]:
        """Scored fact records for a question, best first: {fact, name, score,
        valid_at, invalid_at}. `score` is an absolute on-target cosine the brain
        reports but does NOT threshold. (The brain also returns faithful episode
        bodies; this client surfaces the facts.) Pass group_id for a non-default graph."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if group_id:
            params["group_id"] = group_id
        return self._request("GET", "/recall", params=params).get("facts", [])

    def profile(self, group_id: str | None = None) -> list[dict]:
        """Every captured episode body (the faithful record), newest first.
        Each record is {name, body, source}. Pass group_id for a non-default graph."""
        params = {"group_id": group_id} if group_id else None
        return self._request("GET", "/profile", params=params).get("episodes", [])

    def health(self) -> dict:
        """Liveness probe -> {"ok": true}."""
        return self._request("GET", "/health")


# Backward-compat alias. The old `GraphitiClient` name referred to the retired
# standalone Graphiti MCP client (add_memory/search_nodes/...). The brain's
# contract is now capture/recall/profile; update call sites accordingly — the
# old graph-introspection methods are intentionally not available here.
GraphitiClient = BrainClient
