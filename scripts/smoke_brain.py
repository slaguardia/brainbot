#!/usr/bin/env python3
"""End-to-end smoke test for the brain's API contract.

Captures one fixture, then polls `recall` until the brain returns the captured
content — proving capture → rewrite → extract → recall works end to end.

What it asserts (against the current contract, brain/brain/service.py):
  - POST /capture returns {mode, episodes, topic} with episodes >= 1.
  - GET  /recall returns {facts, episodes}. We check BOTH: the faithful episode
    bodies (which always carry the captured text) and the lossy positive-only
    facts. A hit in either proves retrieval.

Isolation (the brain has no per-call group_id):
    The brain writes to its configured BRAIN_GROUP_ID. To avoid polluting your
    real `brain` graph, run this against a brain configured with
    BRAIN_GROUP_ID=smoketest. The local overlay's `smoke` profile runs one on
    :8101:

        docker compose -f docker-compose.yml -f docker-compose.local.yml \\
            --profile smoke up -d brain-smoke
        BRAIN_URL=http://127.0.0.1:8101 python scripts/smoke_brain.py

    On success the script drops the `smoketest` FalkorDB graph. Pass --keep to
    leave it for inspection.

Usage:
    BRAIN_URL=http://127.0.0.1:8101 python scripts/smoke_brain.py
    BRAIN_URL=https://brain.api.example.com BRAIN_BEARER_TOKEN=... \\
        python scripts/smoke_brain.py --keep
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "migrate"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from graphiti_clients import BrainClient  # noqa: E402

# The graph the smoke writes to. The brain must run with BRAIN_GROUP_ID=smoketest
# for capture to land here. RediSearch treats '-' as NOT, so keep it alphanumeric.
SMOKE_GROUP_ID = "smoketest"

FIXTURE = "Met Alice at Acme on May 9 to discuss the forward-deployed engineering role."
RECALL_QUERY = "Acme"
EXPECT_SUBSTR = "acme"  # the recalled facts/episodes should mention this

EXTRACTION_TIMEOUT_S = 180
# Conservative poll interval so the smoke fits inside Voyage's free-tier rate
# limit (3 RPM without a card on file). Override with SMOKE_POLL_INTERVAL_S.
POLL_INTERVAL_S = int(os.environ.get("SMOKE_POLL_INTERVAL_S", "25"))


def env() -> tuple[str, dict[str, str]]:
    base_url = os.environ.get("BRAIN_URL")
    if not base_url:
        sys.exit("BRAIN_URL not set (e.g. http://127.0.0.1:8101 for the smoke brain)")
    headers = {"Accept": "application/json"}
    bearer = os.environ.get("BRAIN_BEARER_TOKEN")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    elif base_url.startswith("https://"):
        print(
            "WARNING: BRAIN_BEARER_TOKEN unset but BRAIN_URL is https — Caddy will 401.",
            file=sys.stderr,
        )
    return base_url.rstrip("/"), headers


def wait_for_recall(base_url: str, headers: dict, query: str, expect: str, timeout_s: int) -> dict | None:
    """Poll GET /recall until an episode body or a fact mentions `expect`."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(f"{base_url}/recall", params={"q": query, "limit": 10}, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        hay = " ".join(
            [e.get("body", "") for e in data.get("episodes", [])]
            + [f.get("fact", "") for f in data.get("facts", [])]
        ).lower()
        if expect.lower() in hay:
            return data
        time.sleep(POLL_INTERVAL_S)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="leave the smoketest graph populated (default: drop it)")
    args = parser.parse_args()

    base_url, headers = env()
    client = BrainClient(base_url=base_url, bearer=os.environ.get("BRAIN_BEARER_TOKEN"))

    result = client.capture(FIXTURE)
    print(f"captured: mode={result.get('mode')} episodes={result.get('episodes')} topic={result.get('topic')!r}")
    if not result.get("episodes"):
        sys.exit(f"capture returned no episodes: {result}")

    data = wait_for_recall(base_url, headers, RECALL_QUERY, EXPECT_SUBSTR, EXTRACTION_TIMEOUT_S)
    if data is None:
        sys.exit(f"recall('{RECALL_QUERY}') never surfaced '{EXPECT_SUBSTR}' within {EXTRACTION_TIMEOUT_S}s")
    print(f"recall('{RECALL_QUERY}'): {len(data.get('facts', []))} facts, {len(data.get('episodes', []))} episodes")
    if data.get("episodes"):
        print(f"  episode: {data['episodes'][0].get('body', '')[:120]}")
    if data.get("facts"):
        top = data["facts"][0]
        print(f"  top fact: [{top.get('score')}] {top.get('fact')}")
    print("smoke OK: capture → recall round-trip works")

    if not args.keep:
        from reset_brain import drop_graph  # noqa: WPS433
        print(f"cleanup: dropped graph '{SMOKE_GROUP_ID}' ({drop_graph(SMOKE_GROUP_ID)})")
    else:
        print(f"--keep: smoketest graph left populated (group_id='{SMOKE_GROUP_ID}')")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
