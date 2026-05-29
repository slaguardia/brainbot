#!/usr/bin/env python3
"""Smoke test for the ingest CLI (scripts/ingest.py).

Exercises three ingest modes in sequence against an isolated `smoke-test`
graph, then drops the graph on success:

1. stdin → one episode
2. single file → one episode
3. markdown file with --split headings → multiple episodes

Each step waits for the matching entity to appear in search before
moving on. The smoke runs the real ingest.py subprocess (not an import)
so it covers argv parsing + stdin handling end-to-end.

Usage:
    BRAIN_URL=http://127.0.0.1:8100 python scripts/smoke_ingest.py
    python scripts/smoke_ingest.py --keep    # leave the graph populated for inspection
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "migrate"))
sys.path.insert(0, str(ROOT / "scripts"))

from graphiti_clients import GraphitiClient  # noqa: E402
from reset_brain import drop_graph  # noqa: E402

SMOKE_GROUP_ID = "smoketest"  # RediSearch treats '-' as NOT; keep alphanumeric
INGEST = ROOT / "scripts" / "ingest.py"

EXTRACTION_TIMEOUT_S = 240
POLL_INTERVAL_S = int(os.environ.get("SMOKE_POLL_INTERVAL_S", "10"))


def run_ingest(stdin: str | None, *args: str) -> None:
    """Run the ingest CLI, forwarding env + asserting success."""
    env = {**os.environ, "GRAPHITI_GROUP_ID": SMOKE_GROUP_ID}
    result = subprocess.run(
        ["python3", str(INGEST), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(
            f"ingest.py exited {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    print(result.stdout.strip())


def wait_for_entity(client: GraphitiClient, query: str, label: str) -> None:
    deadline = time.time() + EXTRACTION_TIMEOUT_S
    while time.time() < deadline:
        hits = client.search_nodes(query=query, max_nodes=10)
        names = [h.get("name", "") for h in hits]
        if any(query.lower() in n.lower() for n in names):
            print(f"  ✓ {label}: found {names}")
            return
        time.sleep(POLL_INTERVAL_S)
    sys.exit(f"  ✗ {label}: no '{query}' entity within {EXTRACTION_TIMEOUT_S}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="Don't wipe the smoke-test graph on success")
    args = parser.parse_args()

    base_url = os.environ.get("BRAIN_URL")
    if not base_url:
        sys.exit("BRAIN_URL not set (e.g. http://127.0.0.1:8100)")
    client = GraphitiClient(
        base_url=base_url,
        bearer=os.environ.get("BRAIN_BEARER_TOKEN"),
        group_id=SMOKE_GROUP_ID,
    )

    # 1. stdin
    print("\n[1/3] stdin ingest")
    run_ingest(
        "Met Zarya at Nimbus Labs. She's their new principal researcher.\n",
        "--name", "stdin smoke",
    )
    wait_for_entity(client, "Nimbus Labs", "stdin entity")

    # 2. single file
    print("\n[2/3] single-file ingest")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("Quarterly review with Pemberton & Co — they renewed their contract.\n")
        single_path = f.name
    try:
        run_ingest(None, single_path)
        wait_for_entity(client, "Pemberton", "single-file entity")
    finally:
        os.unlink(single_path)

    # 3. markdown with heading split
    print("\n[3/3] markdown --split headings")
    md = (
        "# Smoke planning doc\n\n"
        "Intro paragraph (becomes a prelude episode).\n\n"
        "## Vendors\n\n"
        "Talked to Hexadyne about provisioning tooling.\n\n"
        "## Hiring\n\n"
        "Iris from the design pool is interviewing next week.\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(md)
        md_path = f.name
    try:
        run_ingest(None, md_path, "--split", "headings")
        wait_for_entity(client, "Hexadyne", "headings split entity #1")
        wait_for_entity(client, "Iris", "headings split entity #2")
    finally:
        os.unlink(md_path)

    if not args.keep:
        print(f"\ncleanup: {drop_graph(SMOKE_GROUP_ID)}")
    else:
        print(f"\n--keep: leaving '{SMOKE_GROUP_ID}' graph populated")

    print("\nall ingest paths green ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
