#!/usr/bin/env python3
"""Wipe a FalkorDB graph clean.

Most useful for the smoke tests (which target a dedicated `smoke-test`
graph). Also runnable as a CLI for manual cleanup, with a confirmation
prompt to avoid accidentally nuking the real `brain`.

Usage:
    # delete the smoke graph (used by smoke_brain.py and smoke_ingest.py)
    python scripts/reset_brain.py --graph smoketest

    # delete your real brain (requires --force; will refuse otherwise)
    python scripts/reset_brain.py --graph brain --force

    # show what graphs exist + their sizes
    python scripts/reset_brain.py --list

Defaults: --graph smoketest, no --force needed for that graph. Any
other graph name requires --force.

Talks to FalkorDB directly via `docker exec`. Not designed for the VPS
path — there you'd ssh into the box and run the same command.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

DEFAULT_CONTAINER = "falkordb"
SAFE_TO_DROP_WITHOUT_FORCE = {"smoketest"}


def _docker_exec(*redis_cli_args: str, container: str = DEFAULT_CONTAINER) -> str:
    if shutil.which("docker") is None:
        sys.exit("docker not found on PATH — this script only works on the host")
    result = subprocess.run(
        ["docker", "exec", container, "redis-cli", *redis_cli_args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(f"redis-cli failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def list_graphs(container: str = DEFAULT_CONTAINER) -> list[str]:
    out = _docker_exec("GRAPH.LIST", container=container)
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def node_count(graph: str, container: str = DEFAULT_CONTAINER) -> int:
    out = _docker_exec(
        "GRAPH.QUERY", graph, "MATCH (n) RETURN count(n)", container=container
    )
    # FalkorDB's redis-cli output for GRAPH.QUERY is multi-line: header,
    # values, then metadata. The numeric value lands on its own line.
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    return 0


def drop_graph(graph: str, container: str = DEFAULT_CONTAINER) -> str:
    """Delete the graph. Returns a short summary string for logging."""
    if graph not in list_graphs(container):
        return f"graph '{graph}' did not exist; nothing to drop"
    before = node_count(graph, container)
    _docker_exec("GRAPH.DELETE", graph, container=container)
    return f"removed {before} node(s)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", default="smoketest", help="Graph name to delete (default: smoketest)")
    parser.add_argument("--container", default=DEFAULT_CONTAINER, help="FalkorDB container name (default: falkordb)")
    parser.add_argument("--force", action="store_true", help="Required for any --graph other than smoke-test")
    parser.add_argument("--list", action="store_true", help="List graphs + sizes and exit (no deletion)")
    args = parser.parse_args()

    if args.list:
        graphs = list_graphs(args.container)
        if not graphs:
            print("(no graphs)")
            return 0
        for g in graphs:
            print(f"  {g}\t{node_count(g, args.container)} nodes")
        return 0

    if args.graph not in SAFE_TO_DROP_WITHOUT_FORCE and not args.force:
        sys.exit(f"refusing to drop '{args.graph}' without --force (only {sorted(SAFE_TO_DROP_WITHOUT_FORCE)} are safe by default)")

    print(drop_graph(args.graph, args.container))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
