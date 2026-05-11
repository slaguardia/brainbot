"""Tiny MCP-over-HTTP client for the Graphiti MCP server.

The Graphiti MCP image at zepai/graphiti-mcp:latest exposes a FastMCP
JSON-RPC endpoint at /mcp/ (not a REST API). Every operation is a
tools/call invocation. This client wraps that for the two tools we
need from the migrator: add_memory and search_nodes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import requests


class GraphitiClient:
    def __init__(
        self,
        base_url: str,
        bearer: str | None = None,
        group_id: str = "brain",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.group_id = group_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
        )
        if bearer:
            self.session.headers["Authorization"] = f"Bearer {bearer}"

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        r = self.session.post(f"{self.base_url}/mcp/", json=body, timeout=self.timeout)
        r.raise_for_status()
        return _parse_mcp_response(r)

    def add_memory(
        self,
        name: str,
        episode_body: str,
        source: str = "text",
        source_description: str | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "name": name,
            "episode_body": episode_body,
            "group_id": self.group_id,
            "source": source,
        }
        if source_description:
            args["source_description"] = source_description
        return self._call_tool("add_memory", args)

    def search_nodes(
        self,
        query: str,
        max_nodes: int = 10,
        entity_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        args: dict[str, Any] = {
            "query": query,
            "group_ids": [self.group_id],
            "max_nodes": max_nodes,
        }
        if entity_types:
            args["entity_types"] = entity_types
        result = self._call_tool("search_nodes", args)
        return result.get("nodes", []) or []


def _parse_mcp_response(response: requests.Response) -> dict[str, Any]:
    """Unwrap an MCP JSON-RPC response.

    The server may reply with plain JSON or with text/event-stream.
    For tools/call we expect exactly one final response message.
    """
    content_type = response.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        message = _extract_sse_final_message(response.text)
    else:
        message = response.json()

    if "error" in message:
        raise RuntimeError(f"MCP error: {message['error']}")

    result = message.get("result", {})
    content_blocks = result.get("content") or []
    for block in content_blocks:
        if block.get("type") == "text":
            try:
                return json.loads(block.get("text", "{}"))
            except json.JSONDecodeError:
                return {"text": block.get("text", "")}
    return result


def _extract_sse_final_message(stream_text: str) -> dict[str, Any]:
    """Parse an SSE stream and return the last JSON-RPC message.

    MCP streamable-HTTP responses are SSE-framed: each event has a
    'data: <json>' line. We only need the final response message.
    """
    last_json: dict[str, Any] = {}
    for line in stream_text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            last_json = json.loads(payload)
        except json.JSONDecodeError:
            continue
    return last_json
