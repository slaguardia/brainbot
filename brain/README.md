# brain service

The smart core. A **Postgres + pgvector document store** (no graph DB, no
write-time LLM) that serves the brain's reusable intelligence interface over two
faces — plain HTTP and MCP — on port 8100:

- `POST /ingest {url}` — fetch a Notion page, upsert it as a **source**, and
  re-derive its **chunks** (wipe-replace). Capture = human edit = re-sync are the
  same operation.
- `GET /recall?q=&scope=&k=` — targeted hybrid retrieval: cosine (pgvector) +
  full-text (`tsvector`), fused with Reciprocal Rank Fusion. Top-k sections.
- `GET /profile?scope=&budget=` — domain dump: every chunk under a path prefix,
  assembled into one structured `Context`.
- `GET /map?scope=` — domain discovery: the `(path, title)` source tree.
- `GET /health` — process liveness.

The same reads are exposed as MCP tools (`recall`, `profile`, `map`) at `/mcp`
for Claude Code.

**Consumer contract = `recall(query)` only.** Dumb consumer apps (scout, …) ask a
question and get the relevant chunks; they never need to know the brain's folder
structure (a *scope*). `profile(scope)` and `map(scope)` are **not consumer
endpoints** — they're brain-side machinery (`map` → sync reconciliation + maintenance;
`profile` → self-enrichment: assemble a domain, distill a digest that `recall` then
surfaces) and owner tools (the authed PWA browsing your own folders). See the design
doc's "Brain ↔ consumer interface" correction for the rationale.

## What the brain is

Sources (docs) are **canonical**; their text is split into **chunks**, embedded
with Voyage, and stored in Postgres + pgvector. Reads are pure retrieval — there
is no synthesis, no LLM, no graph. This is a document/vector RAG substrate:

| Table | Holds | Notes |
|---|---|---|
| `sources` | one row per doc/capture/notion_page | `raw_text` is the canonical, human-edited content; `path` is the materialized ancestry (`Career/Job Search/Target Role`); `parent_id` mirrors the source tree. |
| `chunks` | one row per **section** of a source | `text` carries the meaning (the consumer is an LLM — no polarity/strength/typed columns); `embedding vector(512)`; a generated `fts tsvector` for lexical search. `ON DELETE CASCADE` makes wipe-replace a one-liner. |

Phase 1 chunking is deliberately trivial: the **whole page = one chunk**
(position 0, heading = page title). Section-splitting is a later refinement.

## Why this shape (the architecture decision)

The brain used to be a graph (graphiti-core over FalkorDB). Looking at the actual
read path, the graph was never used as a graph — `recall` did hybrid
semantic+BM25 search with **zero multi-hop traversal**, and node-distance
reranking was disabled (the graph was hub-shaped). It was a document/vector
workload wearing a graph costume. The only machinery graphiti genuinely bought —
dedup and bi-temporal invalidation — is **dissolved** by the source-of-truth
model: a source owns its chunks, and re-ingest wipes-and-replaces them, so
currency is guaranteed by construction (no `invalid_at` logic, no write-time
entity resolution). See [`../plans/document-substrate-exploration.md`](../plans/document-substrate-exploration.md)
for the full rationale.

This is also the project's thesis made real: **one smart brain, many thin
consumers.** The PWA backend is a dumb proxy; consumers are read-only.

## The ingest pipeline

```
Notion page (POST /ingest {url})
  → fetch_page(url): title + blocks-flattened-to-markdown + path (ancestor chain)
  → upsert_source(): UPSERT the source row (recompute path), bump version
  → wipe-replace:    DELETE this source's chunks
  → embed():         Voyage embeds the chunk text (batched)
  → INSERT:          one chunk row (Phase 1: whole page) with its vector
```

No fact-extraction LLM, no schema-tagging, no decomposition. Splitting a source
into chunks is string work; embedding is the only external call. Re-posting the
same URL is idempotent and always current.

## The reads

- **`recall(query, scope)`** — a semantic select (cosine `<=>` over the HNSW
  index) and a lexical select (`ts_rank` over the GIN `tsvector`), each
  path-prefix-scoped by `sources.path` and capped, then fused with RRF (`c=60`).
  Returns top-k `Chunk{heading, text, score, path}`.
- **`profile(scope, budget)`** — pulls every chunk under the `scope` path prefix
  ordered by `(path, position)` and rebuilds the subtree into structured markdown
  with provenance. Returns the `Context{text, sources, truncated}` contract. If
  the slice exceeds `budget` it degrades to recall-within-scope and flags
  `truncated=True` rather than silently cutting.
- **`map(scope)`** — `SELECT path, title FROM sources WHERE path LIKE $scope`, so
  a consumer that doesn't know its scope can discover it.

All reads are read-only. Writes come only from sources (ingest / re-sync).

## Modules

| File | Responsibility |
|---|---|
| `brain/config.py` | env config (`PG_DSN`, `VOYAGE_API_KEY`, `BRAIN_EMBED_MODEL`, `NOTION_TOKEN`) + `EMBED_DIM`. |
| `brain/db.py` | the single asyncpg pool (pgvector registered per connection) + `apply_schema` (the idempotent DDL). |
| `brain/embed.py` | `embed(texts)` — Voyage, batched. |
| `brain/notion.py` | `fetch_page(url) -> {title, text, path}`. |
| `brain/store.py` | `upsert_source` / `recall` / `profile` / `map_` and the `Chunk` / `Context` shapes. |
| `brain/api.py` | the FastMCP app: custom HTTP routes + the MCP tools. |

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
curl -s 'localhost:8100/profile?scope=Career/Job%20Search/Target%20Role'
curl -s 'localhost:8100/map'
```

End-to-end smoke: [`../scripts/smoke_substrate.py`](../scripts/smoke_substrate.py)
ingests a Notion page then asserts recall/profile/map return its chunk.

## Known gaps / deliberate Phase-1 limits

- **Whole-page chunking.** Phase 1 stores each page as one chunk. Section-aware
  splitting (heading-based, with self-contained sections) is the planned
  refinement — the schema (`heading`, `position`) already supports it.
- **Wipe-replace is per whole doc.** Re-ingesting an edited source re-embeds the
  whole page. Diff-and-only-re-embed-changed-sections is a later optimization;
  full re-embed per edited doc is cheap and simplest for now.
- **Read-time dedup, if sources ever overlap.** Per-source chunks mean two
  sources can surface near-duplicate text; the consumer LLM tolerates it. Global
  merged facts (and write-time resolution) are intentionally out of scope.
