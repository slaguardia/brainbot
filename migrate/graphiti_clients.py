"""Brain client — thin typed HTTP interface to the brain service.

The canonical Python client for consumer apps. The brain exposes three
operations over plain HTTP/JSON — capture, recall, profile — plus a health
probe. No MCP and no session handshake here: that face exists too, but it's
for Claude Code / LLM harnesses. Typed consumers use these HTTP routes.

Stdlib + requests only, so an external consumer can copy this single file.
(The filename is historical — it predates the brain-service rename; the class
is `BrainClient`.)

  - capture(text)            -> dict   POST /capture   (decompose + extract; slow)
  - recall(query, limit=20)  -> list   GET  /recall    (scored facts, best first)
  - profile()                -> list   GET  /profile   (all current facts)
  - health()                 -> dict   GET  /health

See docs/consumer-api.md for the full per-operation spec.
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

    def capture(self, text: str) -> dict:
        """Write a thought/note. The brain decomposes it and extracts each
        fact server-side, so this returns after the pipeline finishes (seconds).
        Returns {mode, episodes, topic, facts}."""
        return self._request("POST", "/capture", json={"text": text})

    def recall(self, query: str, limit: int = 20) -> list[dict]:
        """Scored fact records for a question, best first. Each record is
        {fact, name, score, valid_at, invalid_at}. `score` is an absolute
        on-target cosine the brain reports but does NOT threshold — the caller
        decides what's strong enough."""
        return self._request("GET", "/recall", params={"q": query, "limit": limit}).get("facts", [])

    def profile(self) -> list[dict]:
        """Every currently-true fact about the user, newest first (unscored).
        Each record is {fact, name, valid_at, invalid_at}."""
        return self._request("GET", "/profile").get("facts", [])

    def health(self) -> dict:
        """Liveness probe -> {"ok": true}."""
        return self._request("GET", "/health")


# Backward-compat alias. The old `GraphitiClient` name referred to the retired
# standalone Graphiti MCP client (add_memory/search_nodes/...). The brain's
# contract is now capture/recall/profile; update call sites accordingly — the
# old graph-introspection methods are intentionally not available here.
GraphitiClient = BrainClient
