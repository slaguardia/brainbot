---
name: test-brain
description: Test the brainbot brain service end-to-end — ingest Notion sources, evaluate recall quality and profile faithfulness, smoke-test recall/profile/map, or wipe and re-seed. Use whenever validating the brain after a change, or checking how source data chunks and recalls.
---

# Testing the brain

The brain service (`brain/`) is a **Postgres + pgvector document store** (no graph
DB, no write-time LLM): sources are ingested, split into chunks, embedded with
Voyage, and recalled by hybrid cosine + full-text search. This skill is how to
exercise and evaluate it. Design context lives in `docs/brain-architecture.md` and
`docs/brain.md` — read them if a result is surprising.

## Stack + prerequisites

```sh
cd compose && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
curl -sS http://127.0.0.1:8100/health      # -> {"ok":true}
```

- Brain is at **http://127.0.0.1:8100** locally (the local overlay maps it). On VPS it's behind Caddy at `brain.api.{domain}` with a bearer.
- Backend is Postgres + pgvector (database `brain`). Inspect the substrate directly with `psql postgresql://brain:<pw>@127.0.0.1:5432/brain` (the local overlay exposes 5432). There is no graph, no `group_id`, no extraction queue.
- `/ingest` needs `NOTION_TOKEN` set (in `compose/.env`) and the page shared with the integration.

## Interfaces

| Call | What | Notes |
|---|---|---|
| `POST /ingest {url}` | fetch a Notion page → upsert source → re-derive chunks (wipe-replace) | idempotent: re-posting the same URL replaces its chunks. One chunk per heading section. |
| `GET /recall?q=...&scope=...&k=N` | top-k sections, hybrid cosine + full-text fused by RRF | each `Chunk` has `id, heading, text, score, path`. `scope` is a `path` prefix. |
| `GET /doc?id=...` | one whole document by stable id | `{id, title, path, version, text}` — `text` is the stored doc verbatim (byte-exact); `version` moves iff title/text change. 404 unknown id. |
| `GET /profile?scope=...&budget=N` | every chunk under a path, assembled into one `Context` | returns `Context{text, sources, truncated}`. Completeness over precision. |
| `GET /map?scope=...` | the source tree | list of `{id, title, path, parent_id, version}` — consumer discovery (ids to pin, versions to diff). |

MCP face (for Claude Code) is the same reads at `/mcp` (tools `recall`, `doc`, `profile`, `map`).

## Wiping / re-seeding

There is no graph to clear. To wipe, truncate the tables (cascades to chunks):

```sh
psql postgresql://brain:<pw>@127.0.0.1:5432/brain -c 'TRUNCATE sources CASCADE;'
```

Re-seed by re-ingesting the source URLs with `POST /ingest`.

## Gotchas (learned the hard way — don't relearn them)

- **Re-ingest is wipe-replace, per source.** Re-posting a URL deletes that source's chunks and re-inserts fresh — the source is always current, never appended. Editing the canonical doc then re-ingesting is the update path.
- **Scores are compressed** with the `voyage-3-lite` embedder (~0.35 on-topic, ~0.20 off-topic — not 0.9). Judge by the **relative gap**, not the absolute number. A bigger embedder widens it (deferred).
- **Chunking is section-based.** One chunk per markdown heading section (`_split_sections`); preamble before the first heading chunks under the page title, and a page with no headings stays a single whole-page chunk. Sources ingested before this landed may still be whole-page until re-ingested.
- **`profile(scope)` can flag `truncated`.** If a scope's chunks exceed the budget it degrades to recall-within-scope and sets `truncated=True` rather than silently cutting. Check the flag.

## Eval flow (quality check with real data)

1. **Wipe** so you start clean: `psql ... -c 'TRUNCATE sources CASCADE;'`
2. **Ingest** the source(s). Share the Notion page with the integration, then:
   `curl -sS -X POST http://127.0.0.1:8100/ingest -H 'Content-Type: application/json' -d '{"url":"https://www.notion.so/<page>"}'`
   (re-run per URL; each is idempotent wipe-replace).
3. **Map check** — `curl -sS 'http://127.0.0.1:8100/map'` — confirm the expected `path`s/titles are present (the domain tree built from the Notion parent chain).
4. **Profile check** — `curl -sS 'http://127.0.0.1:8100/profile?scope=Career/Job%20Search/Target%20Role'` — eyeball faithfulness:
   - Are the **gates** present (e.g. target verticals, the avoid-list)?
   - Did **high-signal** content survive (e.g. TS/SCI clearance)?
   - Is the assembled `text` faithful to the source doc (no editorializing)?
   - Is `truncated` set, and if so, what dropped?
5. **Recall battery** — on-topic queries should score notably higher than an off-topic control:
   ```sh
   curl -sS 'http://127.0.0.1:8100/recall?q=what+stage+of+company&k=5'
   curl -sS 'http://127.0.0.1:8100/recall?q=what+does+the+user+avoid&k=5'
   curl -sS 'http://127.0.0.1:8100/recall?q=favorite+pizza+topping&k=5'   # off-topic control → all low
   ```
6. **Report**: faithfulness, recall separation (on-topic vs control), and whether map/profile cover the expected scopes.

## Smoke flow (plumbing check, deterministic)

For "does the pipeline work" rather than "is my data good," use the end-to-end smoke script, which ingests a Notion page then asserts recall/profile/map return its chunk:

```sh
python3 scripts/smoke_substrate.py
```
