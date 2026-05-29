#!/usr/bin/env python3
"""Smoke test for the ingest CLI (scripts/ingest.py).

Exercises three ingest modes in sequence, then drops the graph on success:

1. stdin → one capture
2. single file → one capture
3. markdown file with --split headings → multiple captures

After each step it polls GET /recall (scoped to the smoketest graph) and checks
that the ingested content comes back — in the faithful episode bodies and/or the
extracted facts. Runs the real ingest.py subprocess (not an import) so it covers
argv parsing + stdin handling.

Isolation: ingest is run with `--group-id smoketest` and recall is scoped the
same way, so the smoke runs against your normal brain without touching the real
`brain` graph. Cleanup drops the smoketest FalkorDB graph.

Usage:
    BRAIN_URL=http://127.0.0.1:8100 python scripts/smoke_ingest.py
    BRAIN_URL=http://127.0.0.1:8100 python scripts/smoke_ingest.py --keep
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "migrate"))
sys.path.insert(0, str(ROOT / "scripts"))

from reset_brain import drop_graph  # noqa: E402

SMOKE_GROUP_ID = "smoketest"  # RediSearch treats '-' as NOT; keep alphanumeric
INGEST = ROOT / "scripts" / "ingest.py"

EXTRACTION_TIMEOUT_S = 240
POLL_INTERVAL_S = int(os.environ.get("SMOKE_POLL_INTERVAL_S", "10"))


def recall_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    bearer = os.environ.get("BRAIN_BEARER_TOKEN")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def run_ingest(stdin: str | None, *args: str) -> None:
    """Run the ingest CLI against the smoketest graph, asserting success."""
    result = subprocess.run(
        ["python3", str(INGEST), "--group-id", SMOKE_GROUP_ID, *args],
        input=stdin,
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    if result.returncode != 0:
        sys.exit(
            f"ingest.py exited {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    print(result.stdout.strip())


def wait_for_recall(base_url: str, query: str, label: str) -> None:
    """Poll GET /recall (smoketest graph) until an episode body or fact mentions `query`."""
    deadline = time.time() + EXTRACTION_TIMEOUT_S
    while time.time() < deadline:
        r = requests.get(
            f"{base_url}/recall",
            params={"q": query, "limit": 10, "group_id": SMOKE_GROUP_ID},
            headers=recall_headers(),
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        hay = " ".join(
            [e.get("body", "") for e in data.get("episodes", [])]
            + [f.get("fact", "") for f in data.get("facts", [])]
        ).lower()
        if query.lower() in hay:
            print(f"  ✓ {label}: recall('{query}') hit")
            return
        time.sleep(POLL_INTERVAL_S)
    sys.exit(f"  ✗ {label}: '{query}' not recalled within {EXTRACTION_TIMEOUT_S}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="Don't drop the smoketest graph on success")
    args = parser.parse_args()

    base_url = os.environ.get("BRAIN_URL")
    if not base_url:
        sys.exit("BRAIN_URL not set (e.g. http://127.0.0.1:8100)")
    base_url = base_url.rstrip("/")

    # 1. stdin
    print("\n[1/3] stdin ingest")
    run_ingest("Met Zarya at Nimbus Labs. She's their new principal researcher.\n", "--name", "stdin smoke")
    wait_for_recall(base_url, "Nimbus", "stdin")

    # 2. single file
    print("\n[2/3] single-file ingest")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("Quarterly review with Pemberton & Co — they renewed their contract.\n")
        single_path = f.name
    try:
        run_ingest(None, single_path)
        wait_for_recall(base_url, "Pemberton", "single-file")
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
        wait_for_recall(base_url, "Hexadyne", "headings split #1")
        wait_for_recall(base_url, "Iris", "headings split #2")
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
