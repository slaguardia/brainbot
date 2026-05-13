#!/usr/bin/env python3
"""End-to-end smoke test for the brain.

Calls add_memory via the MCP server, then polls search_nodes until the
Acme entity appears (entity extraction is queued, not synchronous).
A second invocation with --second posts a follow-up episode that
mentions the same entities and verifies node counts didn't increase
(dedup smoke).

Usage:
    BRAIN_URL=http://127.0.0.1:8000 python scripts/smoke_brain.py
    BRAIN_URL=https://brain.example.com BRAIN_BEARER_TOKEN=... \\
        python scripts/smoke_brain.py [--second]

Default talks to Graphiti's MCP JSON-RPC transport at /mcp/.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "migrate"))

from graphiti_clients import GraphitiClient  # noqa: E402

EPISODE_FIRST = {
    "name": "Meeting: Alice at Acme",
    "episode_body": "Met Alice at Acme on May 9 to discuss the engineering role.",
    "source_description": "smoke-test",
}

EPISODE_SECOND = {
    "name": "Coffee: Alice at Acme",
    "episode_body": "Had coffee with Alice from Acme.",
    "source_description": "smoke-test",
}

EXTRACTION_TIMEOUT_S = 90
POLL_INTERVAL_S = 3


def make_client() -> GraphitiClient:
    base_url = os.environ.get("BRAIN_URL")
    if not base_url:
        sys.exit("BRAIN_URL not set (e.g. http://127.0.0.1:8000)")
    bearer = os.environ.get("BRAIN_BEARER_TOKEN")
    if base_url.startswith("https://") and not bearer:
        print(
            "WARNING: BRAIN_BEARER_TOKEN is unset but BRAIN_URL is https — "
            "Caddy will 401. Set BRAIN_BEARER_TOKEN before re-running.",
            file=sys.stderr,
        )
    return GraphitiClient(
        base_url=base_url,
        bearer=bearer,
        group_id=os.environ.get("GRAPHITI_GROUP_ID", "brain"),
    )


def wait_for_node(client: GraphitiClient, query: str, timeout_s: int) -> list[dict]:
    """Poll search_nodes until at least one match returns or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        nodes = client.search_nodes(query=query, max_nodes=10)
        if nodes:
            return nodes
        time.sleep(POLL_INTERVAL_S)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--second",
        action="store_true",
        help="send the follow-up episode and verify dedup against the first run",
    )
    args = parser.parse_args()

    client = make_client()
    payload = EPISODE_SECOND if args.second else EPISODE_FIRST

    nodes_before: set[str] = set()
    if args.second:
        nodes_before = {
            n.get("name", "") for n in client.search_nodes(query="Acme", max_nodes=20)
        }
        print(f"nodes_before('Acme') = {sorted(nodes_before)}")

    client.add_memory(
        name=payload["name"],
        episode_body=payload["episode_body"],
        source="text",
        source_description=payload["source_description"],
    )
    print(f"queued: {payload['name']}")

    nodes_after = wait_for_node(client, "Acme", EXTRACTION_TIMEOUT_S)
    if not nodes_after:
        sys.exit(f"no Acme node within {EXTRACTION_TIMEOUT_S}s — extraction may have failed")
    names_after = {n.get("name", "") for n in nodes_after}
    print(f"search_nodes('Acme') -> {sorted(names_after)}")

    if args.second:
        new_nodes = names_after - nodes_before
        if new_nodes:
            sys.exit(f"dedup failed: new nodes appeared on second run: {new_nodes}")
        print("dedup OK: no new Acme/Alice nodes after follow-up episode")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
