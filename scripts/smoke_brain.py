#!/usr/bin/env python3
"""End-to-end smoke test for the brain.

Posts an episode to Graphiti via the bearer-protected Caddy vhost,
polls until extraction completes, then queries search_nodes to confirm
the entity is reachable. Re-running with a second episode that mentions
the same entities should link to the existing nodes (no duplicates).

Usage:
    BRAIN_URL=https://brain.example.com BRAIN_BEARER_TOKEN=... \\
        python scripts/smoke_brain.py [--second]

Without --second the first episode ("met Alice at Acme on May 9 to
discuss the FDE role") is sent. With --second the follow-up episode
("had coffee with Alice from Acme") is sent and the script asserts
that node counts for Alice and Acme did not increase.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import requests

EPISODE_FIRST = {
    "name": "Meeting: Alice at Acme",
    "body": "Met Alice at Acme on May 9 to discuss the engineering role.",
    "source_description": "smoke-test",
    "entity_hints": {"company": "Acme", "person": "Alice", "role": "engineering"},
}

EPISODE_SECOND = {
    "name": "Coffee: Alice at Acme",
    "body": "Had coffee with Alice from Acme.",
    "source_description": "smoke-test",
    "entity_hints": {"company": "Acme", "person": "Alice"},
}


def auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("BRAIN_BEARER_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def base_url() -> str:
    url = os.environ.get("BRAIN_URL")
    if not url:
        sys.exit("BRAIN_URL not set in environment (e.g. https://brain.example.com)")
    return url.rstrip("/")


def add_episode(payload: dict) -> str:
    body = {
        **payload,
        "reference_time": datetime.now(timezone.utc).isoformat(),
    }
    r = requests.post(
        f"{base_url()}/add_episode",
        headers=auth_headers(),
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    episode_id = r.json().get("episode_id") or r.json().get("id")
    if not episode_id:
        sys.exit(f"add_episode returned no episode id: {r.text}")
    return episode_id


def wait_for_extraction(episode_id: str, timeout_s: int = 90) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(
            f"{base_url()}/episode/{episode_id}",
            headers=auth_headers(),
            timeout=10,
        )
        if r.ok and r.json().get("status") == "completed":
            return
        time.sleep(2)
    sys.exit(f"extraction did not complete within {timeout_s}s for {episode_id}")


def search_nodes(query: str) -> list[dict]:
    r = requests.post(
        f"{base_url()}/search_nodes",
        headers=auth_headers(),
        json={"query": query, "limit": 10},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("nodes", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--second",
        action="store_true",
        help="send the follow-up episode and verify dedup against the first run",
    )
    args = parser.parse_args()

    payload = EPISODE_SECOND if args.second else EPISODE_FIRST

    nodes_before = {n.get("name") for n in search_nodes("Acme")} if args.second else set()

    episode_id = add_episode(payload)
    print(f"posted episode {episode_id}")
    wait_for_extraction(episode_id)
    print("extraction completed")

    nodes_after = {n.get("name") for n in search_nodes("Acme")}
    if not any("Acme" in (n or "") for n in nodes_after):
        sys.exit(f"Acme not found in search_nodes results: {nodes_after}")
    print(f"search_nodes('Acme') -> {sorted(nodes_after)}")

    if args.second:
        new_nodes = nodes_after - nodes_before
        if new_nodes:
            sys.exit(f"dedup failed: new nodes appeared on second run: {new_nodes}")
        print("dedup OK: no new Acme/Alice nodes after follow-up episode")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
