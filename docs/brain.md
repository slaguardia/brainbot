# brain service

The smart core. A **Postgres + pgvector document store** (no graph DB, no
write-time LLM) that serves the brain's reusable intelligence interface over two
faces — plain HTTP and MCP — on port 8100:

- `POST /ingest {url}` — fetch a Notion page, upsert it as a **source**, and
  re-derive its **chunks** (wipe-replace). Capture = human edit = re-sync are the
  same operation.
- `GET /recall?q=&scope=&k=&complete=` — targeted hybrid retrieval: cosine
  (pgvector) + full-text (`tsvector`), fused with Reciprocal Rank Fusion.
  Top-k sections, each carrying its owning document's stable `id`.
- `GET /doc?id=` — one whole document by stable id: the stored text VERBATIM
  plus title/path and a content-derived `version` stamp. 404 on unknown id.
- `GET /profile?scope=&budget=` — domain dump: every chunk under a path prefix,
  assembled into one structured `Context`.
- `GET /map?scope=` — discovery: the source tree — stable ids, titles, paths,
  parent links, version stamps.
- `GET /health` — process liveness.

The same reads are exposed as MCP tools (`recall`, `doc`, `profile`, `map`) at
`/mcp` for Claude Code.

**Consumer contract = `recall` + `doc` + `map`.** `recall(query)` stays the
search read: dumb consumer apps ask a question and get the relevant chunks.
`doc(id)` and `map()` are the *deterministic* reads: map is where a consumer
discovers the stable document ids (titles/paths are display-only), doc fetches a
pinned document whole and byte-exact, and its `version` stamp is the cache key.
`profile(scope)` remains **not a consumer endpoint** — it assembles/synthesizes
a domain (brain-side self-enrichment + owner browse), which is exactly the line
consumers don't cross: they get faithful content, never an assembled view. See
[`consumer-api.md`](./consumer-api.md) for the consumer contract in full
(cache rules, 404 semantics, what `version` covers).

## What the brain is

Sources (docs) are **canonical**; their text is split into **chunks**, embedded
with Voyage, and stored in Postgres + pgvector. Reads are pure retrieval — there
is no synthesis, no LLM, no graph. This is a document/vector RAG substrate:

| Table | Holds | Notes |
|---|---|---|
| `sources` | one row per doc/capture/notion_page | `id` IS the origin's stable id (the Notion page uuid) — renames never move it; `raw_text` is the canonical, human-edited content (what `/doc` serves verbatim); `path` is the materialized ancestry (`Career/Job Search/Target Role`), display-only; `parent_id` is the origin's parent page/database uuid (provenance, deliberately not an FK — the parent may not be synced). |
| `chunks` | one row per **section** of a source | `text` carries the meaning (the consumer is an LLM — no polarity/strength/typed columns); `embedding vector(512)`; a generated `fts tsvector` for lexical search. `ON DELETE CASCADE` makes wipe-replace a one-liner. |

Chunking is **section-level**: each page splits at its own markdown headings
(one chunk per section, heading + position preserved), so recall discriminates
within a page. A page with no headings stays a single chunk.

## Why this shape (the architecture decision)

The brain used to be a graph (graphiti-core over FalkorDB). Looking at the actual
read path, the graph was never used as a graph — `recall` did hybrid
semantic+BM25 search with **zero multi-hop traversal**, and node-distance
reranking was disabled (the graph was hub-shaped). It was a document/vector
workload wearing a graph costume. The only machinery graphiti genuinely bought —
dedup and bi-temporal invalidation — is **dissolved** by the source-of-truth
model: a source owns its chunks, and re-ingest wipes-and-replaces them, so
currency is guaranteed by construction (no `invalid_at` logic, no write-time
entity resolution). See [`learnings.md`](./learnings.md) Chapter 6 for the full
rationale.

This is also the project's thesis made real: **one smart brain, many thin
consumers.** The PWA backend is a dumb proxy; consumers are read-only.

## The ingest pipeline

```
Notion page (POST /ingest {url})
  → fetch_page(url): title + blocks-flattened-to-markdown + path (ancestor chain)
  → upsert_source(): UPSERT the source row (recompute path), bump version
  → wipe-replace:    DELETE this source's chunks
  → split:           _split_sections() — one section per heading line
  → embed():         Voyage embeds every section (one batched call)
  → INSERT:          one chunk row per section, position = document order
```

No fact-extraction LLM, no schema-tagging, no decomposition. Splitting a source
into chunks is string work; embedding is the only external call. Re-posting the
same URL is idempotent and always current.

## The reads

- **`recall(query, scope)`** — a semantic select (cosine `<=>` over the HNSW
  index) and a lexical select (`ts_rank` over the GIN `tsvector`), each
  path-prefix-scoped by `sources.path` and capped, then fused with RRF (`c=60`).
  Returns top-k `Chunk{id, heading, text, score, path}` — `id` is the owning
  document's stable id, the `doc()` key. With `complete=true` the brain instead
  returns everything IT judges relevant: the semantic arm is trimmed at a
  brain-internal relative similarity floor before fusion (consumers never see a
  score scale), with `k` kept as a safety cap.
- **`doc(id)`** — one row: `{id, title, path, version, text}`. `text` is
  `sources.raw_text` VERBATIM (never reassembled from chunks); `version` is
  `md5` over the served `{title, text}` (length-prefixed title; computed in SQL
  at read time) — it moves iff content/title change, never on a mere re-sync or
  a path (ancestor-rename) change.
- **`profile(scope, budget)`** — pulls every chunk under the `scope` path prefix
  ordered by `(path, position)` and rebuilds the subtree into structured markdown
  with provenance. Returns the `Context{text, sources, truncated}` contract. If
  the slice exceeds `budget` it degrades to recall-within-scope and flags
  `truncated=True` rather than silently cutting.
- **`map(scope)`** — the source tree: `{id, title, path, parent_id, version}`
  per source, ordered by path. `parent_id` is resolved against the synced set
  (null when the origin parent was never synced — ids of unsynced pages don't
  leak); `version` is the same stamp `doc()` serves.

All reads are read-only and knob-free for consumers — `scope`/`k`/`budget`
shape *what* is asked, never how the brain ranks or cuts.

Writes come only from sources (ingest / re-sync).

## Modules

| File | Responsibility |
|---|---|
| `brain/config.py` | env config (`PG_DSN`, `VOYAGE_API_KEY`, `BRAIN_EMBED_MODEL`, `NOTION_TOKEN`) + `EMBED_DIM`. |
| `brain/db.py` | the single asyncpg pool (pgvector registered per connection) + `apply_schema` (the idempotent DDL). |
| `brain/embed.py` | `embed(texts)` — Voyage, batched. |
| `brain/notion.py` | `fetch_page(url) -> {id, title, text, path, parent_id, last_edited_time}`. |
| `brain/store.py` | `upsert_source` / `recall` / `doc` / `profile` / `map_` and the `Chunk` / `Context` shapes. |
| `brain/api.py` | the FastMCP app: custom HTTP routes + the MCP tools. |
| `tests/` | pytest suite — byte-exact `/doc` round-trip, version-stamp semantics, map/recall contracts. Needs `PG_DSN` (derives its own `<dbname>_test` database); skips cleanly without one. |

## Config (env)

| Var | Default | Notes |
|---|---|---|
| `PG_DSN` | `postgresql://brain:brain@postgres:5432/brain` | One asyncpg pool is built from it. In compose it's assembled from `POSTGRES_PASSWORD`. |
| `VOYAGE_API_KEY` | — | required (embeddings) |
| `BRAIN_EMBED_MODEL` | `voyage-3-lite` | 512-dim → `vector(512)`. The column dim and the model must match — change `EMBED_DIM` if you swap. |
| `NOTION_TOKEN` | — | required for `/ingest` (the page must be shared with the integration) |

There is no graphiti, no FalkorDB, no Anthropic/OpenAI, and no write-time LLM
config.

## Run

```sh
# Local: brain + postgres run in docker on the brainnet; brain is exposed on
# 127.0.0.1:8100 via the local overlay.
cd compose
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d brain
curl -s localhost:8100/health
curl -s -X POST localhost:8100/ingest -H 'Content-Type: application/json' \
  -d '{"url":"https://www.notion.so/Some-Page-<id>"}'
curl -s 'localhost:8100/recall?q=which%20locations%20is%20the%20user%20open%20to'
curl -s 'localhost:8100/doc?id=<stable-source-id>'
curl -s 'localhost:8100/profile?scope=Career/Job%20Search/Target%20Role'
curl -s 'localhost:8100/map'
```

End-to-end smoke: [`../scripts/smoke_substrate.py`](../scripts/smoke_substrate.py)
ingests a Notion page then asserts recall/profile/map return its chunk.

## Known gaps / deliberate Phase-1 limits

- **Complete-mode floor is provisional.** `complete=true` trims at a relative
  cosine floor (`_COMPLETE_SIM_FLOOR = 0.85`) validated against a 3-page corpus
  (live A/B on scout's four questions, 2026-06-04); recalibrate as the corpus
  grows. Brain-internal — tuning it never touches the consumer contract.
- **Wipe-replace is per whole doc.** Re-ingesting an edited source re-embeds the
  whole page. Diff-and-only-re-embed-changed-sections is a later optimization;
  full re-embed per edited doc is cheap and simplest for now.
- **Read-time dedup, if sources ever overlap.** Per-source chunks mean two
  sources can surface near-duplicate text; the consumer LLM tolerates it. Global
  merged facts (and write-time resolution) are intentionally out of scope.
