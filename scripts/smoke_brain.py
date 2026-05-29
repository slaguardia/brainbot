#!/usr/bin/env python3
"""End-to-end smoke test for the brain's API contract.

Default: posts one episode via add_memory, polls search_nodes until the
Acme entity appears (extraction is queued, not synchronous), asserts.
With --dedup, posts a second overlapping episode and asserts no new
entities appeared — proves bi-temporal dedup is working.

Isolation: always writes to a dedicated `smoketest` graph so it never
pollutes your real `brain`. (Hyphen-free name is forced by RediSearch:
'-' is the NOT operator and breaks the group_id query.) Pass --keep to
leave the graph for inspection; default behavior drops it on success.

Usage:
    BRAIN_URL=http://127.0.0.1:8000 python scripts/smoke_brain.py
    BRAIN_URL=http://127.0.0.1:8000 python scripts/smoke_brain.py --dedup
    BRAIN_URL=https://brain.api.example.com BRAIN_BEARER_TOKEN=... \\
        python scripts/smoke_brain.py [--dedup] [--keep]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "migrate"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from graphiti_clients import GraphitiClient  # noqa: E402

# group_id must be RediSearch-safe — '-' is interpreted as NOT, so use
# an alphanumeric-only name here.
SMOKE_GROUP_ID = "smoketest"

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

EXTRACTION_TIMEOUT_S = 180
# Polling interval is set conservatively so the smoke fits inside
# embedder free-tier rate limits (Voyage default = 3 RPM without a
# payment method on file). Override with SMOKE_POLL_INTERVAL_S.
POLL_INTERVAL_S = int(os.environ.get("SMOKE_POLL_INTERVAL_S", "25"))


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
    # Smoke always uses the isolated smoke-test group. We deliberately
    # ignore GRAPHITI_GROUP_ID so a developer's local env doesn't redirect
    # the smoke into their real brain graph.
    return GraphitiClient(
        base_url=base_url,
        bearer=bearer,
        group_id=SMOKE_GROUP_ID,
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


def _post_and_wait(client: GraphitiClient, payload: dict, label: str) -> set[str]:
    client.add_memory(
        name=payload["name"],
        episode_body=payload["episode_body"],
        source="text",
        source_description=payload["source_description"],
    )
    print(f"queued: {payload['name']}")
    nodes = wait_for_node(client, "Acme", EXTRACTION_TIMEOUT_S)
    if not nodes:
        sys.exit(f"{label}: no Acme node within {EXTRACTION_TIMEOUT_S}s")
    names = {n.get("name", "") for n in nodes}
    print(f"{label}: search_nodes('Acme') -> {sorted(names)}")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="also post a second overlapping episode and assert no new nodes appear",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the smoketest graph populated after the run (default: wipe)",
    )
    args = parser.parse_args()

    client = make_client()

    names_first = _post_and_wait(client, EPISODE_FIRST, "first ")

    if args.dedup:
        names_second = _post_and_wait(client, EPISODE_SECOND, "second")
        new_nodes = names_second - names_first
        if new_nodes:
            sys.exit(f"dedup failed: new nodes after follow-up episode: {new_nodes}")
        print("dedup OK: no new entities on second overlapping episode")

    if not args.keep:
        from reset_brain import drop_graph  # noqa: WPS433
        dropped = drop_graph(SMOKE_GROUP_ID)
        print(f"cleanup: dropped graph '{SMOKE_GROUP_ID}' ({dropped})")
    else:
        print(f"--keep: smoketest graph left populated (group_id='{SMOKE_GROUP_ID}')")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
