# Brain Architecture

> Living design doc. Point at this during design discussions. Implementation
> details (how to run, config, deps) live in [`README.md`](./README.md); this
> is the *why* and the *shape*. The full migration rationale (why the graph was
> dropped) lives in
> [`../plans/document-substrate-exploration.md`](../plans/document-substrate-exploration.md).

## What the brain is

A **central knowledge hub for a suite of personal apps** — a domain-agnostic
intelligence-gathering library about **one user**. It knows things about the
user; it does not know what any app *does* with that knowledge.

Concretely, it is a **Postgres + pgvector document store**. Sources (docs,
captures, Notion pages) are canonical; their text is split into section-chunks,
embedded with Voyage, and stored. Reads are pure retrieval over those chunks.
There is **no graph DB, no write-time LLM, no extraction/dedup/bi-temporal
machinery** — those were dropped in the document-substrate cutover.

Job-fit ("scout") is the first consumer. Others will follow (reading triage,
calendar prep, etc.). The brain must never learn what a "job" is — that's what
lets it serve all of them.

## The three-layer model

```
┌──────────────────────────────────────────────────────────────┐
│ APP  (scout, …)                                                │
│   common intelligence library:   TASK  →  scope/query          │
│     "to judge this company I need the user's job-hunting        │
│      profile: verticals, stage, location, dealbreakers"        │
│   app agent:   context → reasoning → DECISION                   │
│     synthesizes the assembled context, applies gates →         │
│     pursue / skip / maybe                                       │
└───────────────┬───────────────────────────▲──────────────────┘
                │ scope / query              │ Context (assembled)
                ▼                             │
┌──────────────────────────────────────────────────────────────┐
│ BRAIN  (this service)                                          │
│   recall(query, scope) · profile(scope) · map(scope)          │
│     librarian: retrieves + assembles faithful content,         │
│     never synthesizes, never decides                           │
└───────────────┬───────────────────────────▲──────────────────┘
                │ ingest (sources only)       │ SQL + vector + FTS
                ▼                             │
┌──────────────────────────────────────────────────────────────┐
│ Postgres + pgvector                                            │
│   sources (canonical docs) + chunks (sections, embedded)       │
│   HNSW (semantic) · GIN tsvector (lexical) · path-prefix scope │
└──────────────────────────────────────────────────────────────┘
```

**Division of responsibility:**
- **App's intelligence library** — turns a *task* into the *scope or query* it
  needs, and owns reasoning over the returned `Context`.
- **Brain** — retrieves the *content relevant to a query* and *assembles* it. It
  is a **librarian**: no synthesis, no inference, no decisions. Assembly (gather
  + arrange the human's structure) is librarian work; interpretation is not.
- **App agent** — synthesizes the returned context into a *decision*.

Line in one sentence: **the brain hands back what it knows; the app reasons and
decides.**

## Interfaces

Three reads (plus `/ingest` and `/health`). All reads are **read-only for
consumers** — writes come only from sources.

| Operation | Status | Shape | Notes |
|---|---|---|---|
| `recall(query, scope=None)` | built | query → top-k `Chunk`s | Hybrid: cosine (pgvector `<=>`) + full-text (`tsvector`), each path-scoped, fused with RRF (`c=60`). For ad-hoc lookups and large-brain fallback. |
| `profile(scope, budget)` | built | scope → one assembled `Context` | Every chunk under the `path` prefix, ordered, rebuilt into structured markdown with provenance. Completeness over precision — the scout's primary call. Degrades to recall-in-scope past `budget`, flagging `truncated`. |
| `map(scope=None)` | built | scope → `(path, title)` tree | Domain discovery, so a consumer that doesn't know its scope can find it. |
| `ingest(url)` | built | Notion URL → source + chunk(s) | Fetch → upsert source → wipe-replace chunks → embed. Capture = edit = re-sync. |

Decision (settled): **there is no `ask` method.** The brain is a librarian (no
synthesis), so "ask the brain" *is* `recall` / `profile` — the app reasons over
the returned content itself. A synthesizing `ask` would pull reasoning into the
brain, which we explicitly don't want.

Two faces, one service: HTTP (`/ingest`, `/recall`, `/profile`, `/map`) for apps,
MCP (`/mcp`, tools `recall`/`profile`/`map`) for Claude Code.

### The reusable contract

Both reads return one type — the thing every consumer app codes against:

```
Context { text:      str   # assembled, structured markdown
          sources:   list  # provenance: (path, source_id, title, last_edited)
          truncated: bool } # was the slice cut to fit budget?
```

(`recall` additionally returns the per-`Chunk` list with `heading/text/score/path`.)

## How the brain works internally

- **Ingest:** `fetch_page(url)` returns `{title, text, path}` — page blocks
  flattened to markdown, plus the materialized ancestry from the parent chain.
  `upsert_source` UPSERTs the source row (recomputing `path`, bumping `version`),
  then **wipe-replaces** its chunks: `DELETE` then re-`INSERT` with fresh Voyage
  embeddings. Phase 1 stores the whole page as one chunk.
- **Storage:** Postgres + pgvector, the only persistent store. `sources` holds
  canonical text + `path`; `chunks` holds section text + `embedding vector(512)`
  + a generated `fts tsvector`. `ON DELETE CASCADE` makes wipe-replace a one-liner.
- **Recall:** cosine select + full-text select, path-prefix scoped, fused by RRF.
- **Profile:** gather chunks under a scope, assemble into structured markdown.

## Currency by construction (why no bi-temporal logic)

Sources are the source of truth; chunks are a derived, disposable index FK'd to
their source. Editing or re-syncing a source does `DELETE FROM chunks WHERE
source_id = $x` then re-derives — so **only current chunks ever exist**. This
dissolves two things the old graph needed:

- **No bi-temporal invalidation.** There's no `invalid_at` filter because stale
  chunks are deleted, not superseded. The staleness problem is dissolved, not
  solved. (The trade — losing "what did I believe last month?" — is wanted; if
  history is ever needed it belongs at the doc-version level, not in chunks.)
- **No write-time entity resolution.** Because chunks are owned by a source and
  re-derived on edit, there's no merge/dedup machinery at write time. Per-source
  chunks may surface near-duplicates at read time; the consumer LLM tolerates it.

## Scope = the source tree (how domains stay separated)

Domain is **position in the source hierarchy** (`sources.path`), not a single
document. Notion's nesting is inherited for free as each source's `path`
(`Career/Job Search/Target Role`). Recall and profile scope by a **prefix match**
on `path` (`WHERE path LIKE 'Career/%'`) combined with the vector search in one
query — the hard, multi-level domain boundary, with no traversal. Unscoped
search relies on the embedding space itself as a soft domain boundary. Scaling a
domain = a new branch in the tree; no schema change.

## Scope discipline (what we are deliberately NOT doing yet)

- **Whole-page chunking (Phase 1).** Each page is one chunk; section-aware
  splitting is the planned refinement. The schema (`heading`, `position`) already
  supports it.
- **No global-merged facts.** Per-source chunks + read-time tolerance; no
  write-time entity resolution. Revisit only if read-time duplicates become a
  real problem.
- **No reranking / query-transform tuning yet.** RRF over Voyage embeddings is
  the Phase-1 retrieval. A cross-encoder rerank, HNSW tuning, and HyDE are noted
  RAG experiments, not built now.
- **No multi-tenant.** Single user. Multi-human-per-brain is out of scope.

## Settled principles

1. **Document substrate, not a graph.** The graph never traversed; its only real
   value (dedup + bi-temporal) is dissolved by the source-of-truth model. A
   `path` field — not a graph — provides the domain hierarchy.
2. **Postgres + pgvector is the only store.** One engine for relational
   (`sources`/`chunks` + `path`), vectors (HNSW), and full-text (`tsvector`).
3. **No write-time LLM.** Ingest is split + embed + insert. Embedding is the only
   external call; the embedder is pluggable.
4. **Sources are canonical; chunks are derived and disposable.** Currency by
   construction via wipe-replace.
5. **The brain never synthesizes or reasons — librarian only.** "Ask the brain" =
   `recall` / `profile`. All synthesis lives in the consumer.
6. **Read-only for consumers.** Writes come only from sources.

## RAG: the hood is open

The graph setup was a black-box GraphRAG variant. This substrate is textbook RAG
with the pipeline in your hands: chunking, the embedder + dim, the HNSW index,
the cosine query, the `tsvector` lexical arm, and the RRF fusion are all things
you own and can tune/evaluate. Concrete experiments (rerank pass, chunk vs
proposition, HNSW params, hybrid weighting, a recall@k scorecard, query
transforms) are backlogged in the exploration plan, not built in Phase 1.

## Open questions

- **Section-aware re-extract.** Wipe-replace per whole doc is correct but coarse;
  diff-and-only-re-embed-changed-sections is a later optimization (not v1).
- **Closed-set legibility.** "Allowed verticals are exactly these four" must
  survive as a set when chunks split. Phase 1 (whole-page chunk) preserves it
  trivially; revisit when section-splitting lands.
- **Cross-links across branches.** The `path` tree captures containment, not
  sideways Notion relations/backlinks. Fine for an LLM consumer that synthesizes;
  a join table covers light cross-linking if it's ever needed.
