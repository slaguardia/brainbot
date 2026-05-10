#!/usr/bin/env python3
"""UserPromptSubmit hook: prepend relevant brain hits to the prompt.

Behavior:
1. Read prompt from stdin (Claude Code passes hook input as JSON).
2. If BRAIN_INJECT_SCOPE is set and cwd is not under that path, exit 0
   with no changes. If unset, the hook always runs.
3. Query Graphiti search_nodes(query=prompt, limit=5) with an 800ms budget.
4. If hits returned, emit a hookSpecificOutput.additionalContext block on
   stdout that prepends a <relevant-memory> envelope to the prompt.
5. On timeout or any error, log to .claude/logs/inject_memory.log under
   cwd and exit 0 (silent degrade — the prompt still flows).

Required env (set in shell before launching claude):
    BRAIN_URL              e.g. https://brain.example.com
    BRAIN_BEARER_TOKEN     bearer for the Caddy vhost

Optional env:
    BRAIN_INJECT_SCOPE     filesystem path; hook no-ops outside it
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SEARCH_TIMEOUT_S = 0.8
RESULT_LIMIT = 5


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


def _search_nodes(prompt: str) -> list[dict]:
    base_url = os.environ.get("BRAIN_URL")
    token = os.environ.get("BRAIN_BEARER_TOKEN")
    if not base_url or not token:
        _log("missing BRAIN_URL or BRAIN_BEARER_TOKEN; skipping injection")
        return []

    body = json.dumps({"query": prompt, "limit": RESULT_LIMIT}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/search_nodes",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("nodes", []) or []


def _format_block(nodes: list[dict]) -> str:
    lines = ["<relevant-memory>"]
    for node in nodes[:RESULT_LIMIT]:
        name = node.get("name") or node.get("id", "?")
        summary = node.get("summary") or node.get("description") or ""
        lines.append(f"- {name}: {summary}".rstrip())
    lines.append("</relevant-memory>")
    return "\n".join(lines)


def main() -> int:
    prompt, cwd = _read_input()
    if not prompt:
        return 0
    if not _scope_allows(cwd):
        return 0

    try:
        nodes = _search_nodes(prompt)
    except urllib.error.URLError as e:
        _log(f"search_nodes URLError: {e}")
        return 0
    except Exception:
        _log(f"search_nodes exception:\n{traceback.format_exc()}")
        return 0

    if not nodes:
        _log("no hits for prompt; no injection")
        return 0

    block = _format_block(nodes)
    _log(f"injected {len(nodes)} hits")

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
