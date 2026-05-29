#!/usr/bin/env python3
"""Section-aware ingest into the brain service.

Splits a markdown doc on heading boundaries and POSTs each section to the
brain's /capture as a separate capture. This is the workaround for the
"long doc breaks a single capture" gotcha (decompose JSON exceeds max_tokens
and truncates). One section per capture keeps each decompose small.

Usage:
    python3 ingest_doc.py path/to/doc.md
    python3 ingest_doc.py path/to/doc.md --whole     # send as ONE capture (will fail on long docs; for short notes only)
    cat note.txt | python3 ingest_doc.py -           # stdin → one capture

Env:
    BRAIN_URL            default http://127.0.0.1:8100
    BRAIN_BEARER_TOKEN   sent as Authorization: Bearer ... if set (VPS)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BRAIN_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:8100").rstrip("/")
BEARER = os.environ.get("BRAIN_BEARER_TOKEN")


def post_capture(text: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if BEARER:
        headers["Authorization"] = f"Bearer {BEARER}"
    req = urllib.request.Request(
        f"{BRAIN_URL}/capture",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def split_sections(text: str) -> list[str]:
    """Split on markdown heading lines; keep each heading with its body."""
    sections, cur = [], []
    for ln in text.splitlines():
        if ln.lstrip().startswith("#") and cur and any(l.strip() for l in cur):
            sections.append("\n".join(cur).strip())
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        sections.append("\n".join(cur).strip())
    return [s for s in sections if s.strip()]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    whole = "--whole" in sys.argv[1:]
    path = args[0] if args else "-"

    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    if not text.strip():
        sys.exit("empty input")

    chunks = [text] if (whole or path == "-") else split_sections(text)
    print(f"ingesting {len(chunks)} capture(s) into {BRAIN_URL}\n")

    total_facts = 0
    for i, c in enumerate(chunks, 1):
        head = c.splitlines()[0][:50]
        try:
            r = post_capture(c)
            total_facts += r.get("facts", 0) or 0
            print(f"  [{i}/{len(chunks)}] {head:<52} -> {r.get('facts')} facts | {r.get('topic')}")
        except Exception as e:  # noqa: BLE001 — report and continue
            print(f"  [{i}/{len(chunks)}] {head:<52} -> ERROR {e}")
        time.sleep(0.3)

    print(f"\ndone: {total_facts} facts across {len(chunks)} capture(s).")
    print("Extraction drains async — wait ~10s/section before /recall or /profile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
