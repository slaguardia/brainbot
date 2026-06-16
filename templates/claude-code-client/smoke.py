#!/usr/bin/env python3
"""Smoke-test the inject_memory hook against a running brain.

Run from inside a client repo that has .claude/hooks/inject_memory.py
installed per INSTALL.md.

Usage:
  BRAIN_URL=http://127.0.0.1:8100 ./smoke.py "your test query"
  BRAIN_URL=https://brain.api.example.com BRAIN_BEARER_TOKEN=xxx ./smoke.py "query"

Exit 0 if the hook emitted a <relevant-memory> block; 1 otherwise.
BRAIN_BEARER_TOKEN is passed through from the caller's env if set.
"""
import json
import os
import subprocess
import sys


def fail(*msg: str) -> int:
    for line in msg:
        print(line, file=sys.stderr)
    return 1


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "test"
    hook = os.environ.get("HOOK", ".claude/hooks/inject_memory.py")
    brain_url = os.environ.get("BRAIN_URL", "http://127.0.0.1:8100")

    if not os.access(hook, os.X_OK):
        return fail(
            f"smoke: hook not found or not executable at {hook}",
            "       run from a client repo where step 3 of INSTALL.md is done",
        )

    payload = json.dumps({"prompt": query, "cwd": os.getcwd()})
    print(f"smoke: BRAIN_URL={brain_url}  query={query!r}", file=sys.stderr)

    env = {**os.environ, "BRAIN_URL": brain_url}
    result = subprocess.run(
        [hook], input=payload, capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        return fail(
            f"smoke: hook exited {result.returncode} "
            "(unexpected — hook should always exit 0)"
        )

    out = result.stdout
    if not out:
        return fail(
            "smoke: hook produced no output (no hits, timeout, or error)",
            "       tail .claude/logs/inject_memory.log for details",
        )

    try:
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError) as e:
        return fail(f"smoke: malformed hook output: {e}")

    if "<relevant-memory>" not in ctx:
        return fail("smoke: output missing <relevant-memory> envelope")

    print(ctx)
    print("smoke: ok", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
