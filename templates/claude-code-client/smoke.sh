#!/usr/bin/env bash
# Smoke-test the inject_memory hook against a running brain.
#
# Run from inside a client repo that has .claude/hooks/inject_memory.py
# installed per INSTALL.md.
#
# Usage:
#   BRAIN_URL=http://127.0.0.1:8000 ./smoke.sh "your test query"
#   BRAIN_URL=https://brain.api.example.com BRAIN_BEARER_TOKEN=xxx ./smoke.sh "query"
#
# Exit 0 if the hook emitted a <relevant-memory> block; 1 otherwise.

set -u

QUERY="${1:-test}"
HOOK="${HOOK:-.claude/hooks/inject_memory.py}"
BRAIN_URL="${BRAIN_URL:-http://127.0.0.1:8000}"

if [ ! -x "$HOOK" ]; then
  echo "smoke: hook not found or not executable at $HOOK" >&2
  echo "       run from a client repo where step 3 of INSTALL.md is done" >&2
  exit 1
fi

export BRAIN_URL
# BRAIN_BEARER_TOKEN is passed through if set in the caller's env.

payload="$(QUERY="$QUERY" CWD="$(pwd)" python3 -c '
import json, os
print(json.dumps({"prompt": os.environ["QUERY"], "cwd": os.environ["CWD"]}))
')"

echo "smoke: BRAIN_URL=$BRAIN_URL  query=$(printf '%q' "$QUERY")" >&2

out="$(printf '%s' "$payload" | "$HOOK")"
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "smoke: hook exited $rc (unexpected — hook should always exit 0)" >&2
  exit 1
fi

if [ -z "$out" ]; then
  echo "smoke: hook produced no output (no hits, timeout, or error)" >&2
  echo "       tail .claude/logs/inject_memory.log for details" >&2
  exit 1
fi

if printf '%s' "$out" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    ctx = data["hookSpecificOutput"]["additionalContext"]
except Exception as e:
    print(f"smoke: malformed hook output: {e}", file=sys.stderr)
    sys.exit(1)
if "<relevant-memory>" not in ctx:
    print("smoke: output missing <relevant-memory> envelope", file=sys.stderr)
    sys.exit(1)
print(ctx)
'; then
  echo "smoke: ok" >&2
  exit 0
else
  exit 1
fi
