"""Tiny REST client for the Graphiti MCP server behind Caddy."""

from __future__ import annotations

from typing import Any

import requests


class GraphitiClient:
    def __init__(self, base_url: str, bearer: str | None = None, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if bearer:
            self.session.headers["Authorization"] = f"Bearer {bearer}"

    def add_episode(self, payload: dict[str, Any]) -> str:
        r = self.session.post(
            f"{self.base_url}/add_episode", json=payload, timeout=self.timeout
        )
        r.raise_for_status()
        body = r.json()
        episode_id = body.get("episode_id") or body.get("id")
        if not episode_id:
            raise RuntimeError(f"add_episode returned no id: {body}")
        return episode_id
