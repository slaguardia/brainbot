#!/usr/bin/env python3
"""End-to-end smoke test for the document-substrate brain (US-010).

Drives the brain's HTTP contract against a live service: ingest a real Notion
page, then exercise the three reads — recall, profile, map — and assert the
page's chunk actually comes back. Proves fetch_page -> upsert_source ->
chunk+embed -> recall/profile/map works end to end on Postgres+pgvector.

What it does, in order:
  1. POST /ingest {url}          — fetch the Notion page, upsert it as a source,
                                    re-derive its chunk (wipe-replace). Asserts a
                                    source_id + a path come back.
  2. GET  /recall?q=&scope=      — a query about which locations Steve is open to.
                                    Asserts at least one chunk returns AND that the
                                    ingested page's path is among the hits.
  3. GET  /profile?scope=<path>  — the assembled domain dump for the page's path.
                                    Asserts non-empty assembled text + provenance
                                    naming the source.
  4. GET  /map?scope=            — the (path, title) source tree. Asserts the
                                    ingested page's path is listed.

Required env (the brain must already be running with these — this script only
talks HTTP, it does not read them itself except BRAIN_URL):
  - POSTGRES_PASSWORD   the brain assembles PG_DSN from it in compose; or set
  - PG_DSN              directly if running the brain outside compose.
  - VOYAGE_API_KEY      embeddings (Voyage). Required by the brain to embed.
  - NOTION_TOKEN        the Notion integration token; the page must be shared
                        with that integration or /ingest returns a 4xx.
  - BRAIN_URL           the brain's base URL. Default http://127.0.0.1:8100.

The page to ingest defaults to Steve's "Target role" Notion page; override with
the first positional arg or the SMOKE_PAGE_URL env var.

Usage:
    BRAIN_URL=http://127.0.0.1:8100 python scripts/smoke_substrate.py
    python scripts/smoke_substrate.py https://www.notion.so/Some-Page-<id>
    SMOKE_PAGE_URL=https://www.notion.so/Some-Page-<id> \\
        BRAIN_URL=https://brain.api.example.com BRAIN_BEARER_TOKEN=... \\
        python scripts/smoke_substrate.py
"""

from __future__ import annotations

import argparse
import os
import sys

import requests

# The default page: Steve's "Target role" doc. Overridable by arg or env so the
# smoke isn't pinned to one fixture.
DEFAULT_PAGE_URL = (
    "https://www.notion.so/Target-role-32b7973a54538058b68be43c694fc7cb"
)

# A natural-language query the recall arm should answer from the target-role page.
RECALL_QUERY = "which locations is Steve open to"

HTTP_TIMEOUT_S = 120  # ingest embeds via Voyage, so allow a generous window.


def env() -> tuple[str, dict[str, str]]:
    """Resolve the brain base URL + auth headers. Warns (doesn't fail) if an
    https brain is hit without a bearer — Caddy would 401."""
    base_url = os.environ.get("BRAIN_URL", "http://127.0.0.1:8100").rstrip("/")
    headers = {"Accept": "application/json"}
    bearer = os.environ.get("BRAIN_BEARER_TOKEN")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    elif base_url.startswith("https://"):
        print(
            "WARNING: BRAIN_BEARER_TOKEN unset but BRAIN_URL is https — Caddy will 401.",
            file=sys.stderr,
        )
    return base_url, headers


def ingest(base_url: str, headers: dict, url: str) -> dict:
    """POST /ingest {url} — fetch + upsert + chunk the page. Returns the body."""
    r = requests.post(
        f"{base_url}/ingest",
        json={"url": url},
        headers=headers,
        timeout=HTTP_TIMEOUT_S,
    )
    if not r.ok:
        sys.exit(f"ingest failed: HTTP {r.status_code} {r.text}")
    data = r.json()
    if not data.get("source_id"):
        sys.exit(f"ingest returned no source_id: {data}")
    if not data.get("path"):
        sys.exit(f"ingest returned no path: {data}")
    print(
        f"ingest OK: source_id={data['source_id']} "
        f"path={data.get('path')!r} chunks={data.get('chunks')}"
    )
    return data


def recall(base_url: str, headers: dict, query: str, scope: str | None) -> list[dict]:
    """GET /recall?q=&scope= — top-k hybrid-search sections. Returns the chunks."""
    params = {"q": query}
    if scope:
        params["scope"] = scope
    r = requests.get(
        f"{base_url}/recall", params=params, headers=headers, timeout=HTTP_TIMEOUT_S
    )
    if not r.ok:
        sys.exit(f"recall failed: HTTP {r.status_code} {r.text}")
    return r.json().get("chunks", [])


def profile(base_url: str, headers: dict, scope: str) -> dict:
    """GET /profile?scope= — the assembled domain dump. Returns the Context body."""
    r = requests.get(
        f"{base_url}/profile",
        params={"scope": scope},
        headers=headers,
        timeout=HTTP_TIMEOUT_S,
    )
    if not r.ok:
        sys.exit(f"profile failed: HTTP {r.status_code} {r.text}")
    return r.json()


def map_(base_url: str, headers: dict, scope: str | None) -> list[dict]:
    """GET /map?scope= — the (path, title) source tree. Returns the rows."""
    params = {"scope": scope} if scope else {}
    r = requests.get(
        f"{base_url}/map", params=params, headers=headers, timeout=HTTP_TIMEOUT_S
    )
    if not r.ok:
        sys.exit(f"map failed: HTTP {r.status_code} {r.text}")
    return r.json().get("sources", [])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=os.environ.get("SMOKE_PAGE_URL", DEFAULT_PAGE_URL),
        help="Notion page URL to ingest (default: the Target-role page).",
    )
    args = parser.parse_args()

    base_url, headers = env()
    print(f"brain={base_url}  page={args.url}")

    # 1. Ingest the page.
    ingested = ingest(base_url, headers, args.url)
    path = ingested["path"]

    # 2. Recall: a question about locations Steve is open to. Assert we get a hit
    #    AND that the ingested page is among the results (its chunk came back).
    print(f"\nrecall: {RECALL_QUERY!r}")
    chunks = recall(base_url, headers, RECALL_QUERY, scope=None)
    if not chunks:
        sys.exit("recall returned no chunks — the page's chunk did not come back")
    top = chunks[0]
    print(f"  {len(chunks)} chunk(s); top: [{top.get('score'):.4f}] "
          f"{top.get('heading')!r} path={top.get('path')!r}")
    if not any(c.get("path") == path for c in chunks):
        sys.exit(
            f"recall did not surface the ingested page (path={path!r}); "
            f"got paths {[c.get('path') for c in chunks]}"
        )
    print("  ✓ ingested page chunk present in recall results")

    # 3. Profile: the assembled dump for the page's own path. Assert non-empty
    #    text and that provenance names the source we just ingested.
    print(f"\nprofile: scope={path!r}")
    ctx = profile(base_url, headers, path)
    text = ctx.get("text", "")
    sources = ctx.get("sources", [])
    if not text.strip():
        sys.exit(f"profile returned empty text for scope={path!r}")
    if not any(s.get("path") == path for s in sources):
        sys.exit(
            f"profile provenance missing the ingested page (path={path!r}); "
            f"got {[s.get('path') for s in sources]}"
        )
    print(f"  {len(text)} chars, {len(sources)} source(s), truncated={ctx.get('truncated')}")
    print(f"  text head: {text[:120]!r}")
    print("  ✓ assembled profile contains the ingested source")

    # 4. Map: the source tree. Assert the ingested page's path is listed.
    print("\nmap: (all sources)")
    tree = map_(base_url, headers, scope=None)
    paths = [row.get("path") for row in tree]
    print(f"  {len(tree)} source(s): {paths}")
    if path not in paths:
        sys.exit(f"map did not list the ingested page (path={path!r}); got {paths}")
    print("  ✓ ingested page present in the source tree")

    print("\nsmoke OK: ingest → recall → profile → map round-trip works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
