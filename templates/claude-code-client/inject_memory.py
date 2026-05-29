#!/usr/bin/env python3
"""UserPromptSubmit hook: prepend relevant brain hits to the prompt.

Behavior:
1. Read prompt from stdin (Claude Code passes hook input as JSON).
2. If BRAIN_INJECT_SCOPE is set and cwd is not under that path, exit 0
   with no changes. If unset, the hook always runs.
3. GET <BRAIN_URL>/recall?q=<prompt> on the brain service — one plain-HTTP
   request, no MCP handshake. The brain does the search and returns ranked
   facts. (Replaces the old graphiti MCP search_nodes path.)
4. If hits returned, emit a hookSpecificOutput.additionalContext block on
   stdout that prepends a <relevant-memory> envelope to the prompt.
5. On timeout or any error, log to .claude/logs/inject_memory.log under
   cwd and exit 0 (silent degrade — the prompt still flows).

Uses only stdlib so the hook has no install step beyond copying the file.

Required env (set in shell before launching claude):
    BRAIN_URL              e.g. https://brain.api.example.com  (local: http://127.0.0.1:8100)
    BRAIN_BEARER_TOKEN     bearer for the Caddy vhost (omit for local)

Optional env:
    BRAIN_INJECT_SCOPE     filesystem path; hook no-ops outside it
    BRAIN_INJECT_DISABLE   set to "1" to no-op (kill switch for sensitive sessions)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REQUEST_TIMEOUT_S = 2.5  # single request now; settings.json gives the hook ~3s total
RESULT_LIMIT = 5
MAX_QUERY_BYTES = 2000


def _log_path() -> Path:
    return Path.cwd() / ".claude" / "logs" / "inject_memory.log"


def _log(message: str) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(f"{datetime.utcnow().isoformat()}Z {message}\n")
    except Exception:
        pass


def _scope_allows(cwd: str | None) -> bool:
    scope = os.environ.get("BRAIN_INJECT_SCOPE")
    if not scope:
        return True
    if not cwd:
        return False
    try:
        Path(cwd).resolve().relative_to(Path(scope).expanduser().resolve())
        return True
    except ValueError:
        return False


def _read_input() -> tuple[str, str]:
    raw = sys.stdin.read()
    if not raw.strip():
        return "", ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip(), os.getcwd()
    prompt = payload.get("prompt") or payload.get("user_input") or ""
    cwd = payload.get("cwd") or os.getcwd()
    return prompt, cwd


def _recall_url(prompt: str) -> str:
    base_url = os.environ.get("BRAIN_URL")
    if not base_url:
        raise RuntimeError("BRAIN_URL not set")
    from urllib.parse import urlencode

    qs = urlencode({"q": prompt, "limit": RESULT_LIMIT})
    # The brain service exposes plain-HTTP /recall (no MCP handshake needed).
    return f"{base_url.rstrip('/')}/recall?{qs}"


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = os.environ.get("BRAIN_BEARER_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _recall(prompt: str) -> tuple[list[dict], int]:
    """GET the brain's /recall endpoint. Returns (facts, elapsed_ms).

    One request, no MCP handshake — the brain service does the work and
    returns ranked facts directly.
    """
    url = _recall_url(prompt)
    start = time.monotonic()
    req = urllib.request.Request(url, method="GET", headers=_headers())
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        text = resp.read().decode("utf-8")
    elapsed_ms = int((time.monotonic() - start) * 1000)
    data = json.loads(text) if text else {}
    return data.get("facts", []) or [], elapsed_ms


def _format_block(facts: list[dict]) -> str:
    lines = ["<relevant-memory>"]
    for f in facts[:RESULT_LIMIT]:
        fact = (f.get("fact") or "").strip()
        if fact:
            lines.append(f"- {fact}")
    lines.append("</relevant-memory>")
    return "\n".join(lines)


def main() -> int:
    prompt, cwd = _read_input()
    if not prompt:
        return 0
    if not _scope_allows(cwd):
        return 0
    if os.environ.get("BRAIN_INJECT_DISABLE") == "1":
        return 0

    encoded = prompt.encode("utf-8")
    if len(encoded) > MAX_QUERY_BYTES:
        prompt = encoded[:MAX_QUERY_BYTES].decode("utf-8", errors="ignore")

    try:
        facts, elapsed_ms = _recall(prompt)
    except urllib.error.URLError as e:
        _log(f"recall URLError: {e}")
        return 0
    except Exception:
        _log(f"recall exception:\n{traceback.format_exc()}")
        return 0

    if not facts:
        _log(f"no hits for prompt; no injection (recall took {elapsed_ms}ms)")
        return 0

    block = _format_block(facts)
    _log(f"injected {len(facts)} hits in {elapsed_ms}ms")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": block,
        }
    }
    json.dump(output, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
