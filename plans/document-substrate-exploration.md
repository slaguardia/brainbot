# Plan: Document substrate (source-of-truth docs + derived facts on pgvector)

## Status: intended direction — migration not yet triggered

Captured 2026-05-31 from a design conversation, refined over it. Steve now accepts
the graph DB doesn't earn its keep for this use case (its only real benefit here is
dedup + bi-temporal, **not** relationships) and is **fine leaving graph-DB
experimentation behind** — the remaining hesitation (losing RAG learning) is
resolved by the [RAG section](#rag-what-wed-be-experimenting-with): this substrate
is *more* hands-on RAG, not less. So this is increasingly the **intended refactor
direction**, though the migration itself isn't scheduled/triggered yet (see *When
to pull the trigger*). **Two further refinements (2026-05-31):** facts →
**section-chunks** (no polarity/strength schema — an LLM reads structure from
prose), and the brain is framed as a **reusable intelligence-gathering library**
with two reads — `recall(query)` (lookup) and `profile(scope)` (domain dump,
scout's primary mode); see *Brain ↔ consumer interface*. With that interface now
specced (phased: `recall` + `profile` + `map` in Phase 1, multi-scope assembly
later; consumers read-only), **the design hashout is buttoned up — what's left is
execution (and pulling the trigger).** See also
[`../docs/human-edit-surface.md`](../docs/human-edit-surface.md).

---

## The question that started it

> The benefit of a graph DB is relationships. Does ours earn its keep, or would
> a document store make this simpler?

### What the evidence said

Looking at the actual read path, the graph **is not being used as a graph**:

- `recall()` is `graphiti.search_()` with `COMBINED_HYBRID_SEARCH_RRF` —
  semantic embeddings + BM25, fused, then re-scored by cosine. **Zero multi-hop
  traversal anywhere in the query path.** The only Cypher run is single-hop
  (fetch embeddings for already-found edges; dump live edges for `profile()`).
- `brain/ARCHITECTURE.md` says it out loud: the graph is **hub-shaped**
  (everything hangs off the user node), and **node-distance reranking is
  deliberately disabled** because every concept is 2 hops from every other
  through the user. The star topology means traversal can't improve ranking.

So the "relationships" benefit we'd reach for a graph to get — we don't cash in.
The graph is a fact store queried by vector search. That's a document/vector
workload wearing a graph costume.

### What graphiti *actually* buys us

Not "graph." Three pieces of machinery:

1. **Entity dedup / resolution** — merge "Steve" across N sources into one node.
   *(The genuinely hard one to rebuild.)*
2. **Bi-temporal invalidation** — `valid_at` / `invalid_at`; facts get superseded,
   not overwritten.
3. **Hybrid retrieval** — semantic + BM25 + RRF, already wired.

We never chose FalkorDB; graphiti did. So "switch to a document store" really
means "drop graphiti and re-earn those three." That's the real trade.

---

## Why replacing it is mostly a port, not a rebuild

Graphiti's pipeline is ~7 steps. **Five are storage-agnostic LLM/embedding
calls** that run identically against any backend; only three touch the
store, and all three are *"find similar records"* (a vector index's job), **not
traversal**:

| Step (ingest) | What it is | Needs graph? |
|---|---|---|
| Store episode | save raw text + source + ts | no — a row |
| Entity extraction | LLM → entities | no — LLM call |
| Edge/fact extraction | LLM → facts + `polarity`/`strength` | no — LLM call |
| **Entity resolution (dedup)** | find existing → merge/create | **lookup** (vector) |
| **Edge invalidation** | new fact supersedes old → set `invalid_at` | **lookup** (vector) |
| Embed name + fact | vector for hybrid search | no — embed call |
| Temporal extraction | pull `valid_at` from text | no — LLM call |

| Step (query) | | |
|---|---|---|
| Hybrid search | semantic + BM25 + RRF | **lookup** (vector + FTS) |
| Node-distance rerank | graph BFS | **already disabled** (star) |

Replacing graphiti = keep the whole LLM pipeline, swap three Cypher lookups for
pgvector/SQL lookups.

---

## The proposed substrate (Postgres + pgvector)

Three tables instead of nodes/edges:

```
sources(id, kind, title, raw_text, parent_id FK, path, version, created_at, updated_at)
chunks(id, source_id FK, heading, text, position, embedding vector, created_at)
-- chunks = the source's own SECTIONS — NOT schema-tagged "facts". No
--   polarity/strength/typed columns: the consumer is an LLM that reads structure
--   from the section text. (Earlier drafts had a facts + polarity/strength schema —
--   dropped; see "Brain ↔ consumer interface" for why.)
-- path = materialized ancestry (e.g. 'Career/Job Search/Target Role'); domain
--   scoping is a prefix match on it. parent_id mirrors the source tree (Notion nesting).
```

Per-step swap:

- **Capture / edit** → split the source into its own sections → embed each →
  `INSERT`. No fact-extraction LLM, no schema (see "Brain ↔ consumer interface").
- **Recall** (lookup) → `ORDER BY embedding <=> $q` (semantic) + `to_tsvector` FTS
  (our BM25), fused with RRF in ~20 lines. Reproduces `COMBINED_HYBRID_SEARCH_RRF`.
- **Profile** (domain dump) → gather all chunks under a `path` scope, ordered, and
  assemble into one structured context bundle. Currency is guaranteed by
  construction, so there's no `invalid_at` filter to apply.

Notice chunks are stored as **sections whose text carries the meaning** — which is
*all the consumer (an LLM) needs*. A document store is a more honest representation
of what the brain actually does than the graph is.

---

## The unlock: source-of-truth docs + derived disposable facts

The model that makes all of this click, and that solves the human-edit
requirement the graph never could:

> **Source docs (and every capture, treated as a write-once doc-of-one) are
> canonical and human-edited. Facts are a derived, disposable index FK'd to
> their `source_id`. Editing a source does
> `DELETE FROM facts WHERE source_id = $x` + re-extract. Recall is semantic over
> facts. History lives at the doc-version level, not in the facts.**

Consequences:

- **Currency by construction.** Edit the target-role doc → its old facts vanish →
  re-extract → only current facts exist. **No bi-temporal invalidation logic
  needed** — the staleness problem is dissolved, not solved.
- **Human-edit is trivial.** The human edits the legible *doc*; never touches the
  machine-derived facts. PWA UX = a textarea + save button. No node editor, no
  Cypher, no exposing the machine layer. This is the direct answer to
  [`../docs/human-edit-surface.md`](../docs/human-edit-surface.md).
- **It removes the hard 20% of rolling our own.** Because facts are owned by a
  source and re-derived on edit, we don't need write-time entity-resolution
  machinery. That's why DIY-on-pgvector becomes tractable for a "2-tools" brain.
- **It trades history for currency — on purpose.** Wipe-replace deletes old
  facts, so it can't answer "what did I believe last month?" That's *wanted*
  ("only operate on current context"). If history is ever needed, put it at the
  **doc-version level** (git / a `doc_versions` table) — versioning the legible
  source is a far nicer home for history than fact-level temporal edges.

### Design fork to decide later: per-source vs. global merged facts

If "wants remote work" is derived from *two* sources:

- **Per-source (simple — recommended for a 2-tools brain):** each source owns its
  copy. Wiping one source removes its copy; the other survives. Recall may return
  near-duplicates → **dedup at read time** (collapse by embedding similarity, or
  let the consumer LLM tolerate it — it already filters/synthesizes). Throws away
  the entire write-time entity-resolution problem for a cheap, benign read cost.
- **Global merged (graphiti-like):** one fact row with a list of `source_id`s;
  delete only when the list empties. More correct, but drags write-time
  resolution back in.

Per-source + read-time dedup is the call that keeps DIY easy.

---

## Scalability: how facts stay delineated across many domains

The worry: today we talk about "the target-role doc," but the brain should
capture many domains (career, skills, health, people, preferences…). How do facts
stay separated without graph communities?

**Domain = position in the source hierarchy (the `path`), not a single document.**
Facts inherit their domain from their source's place in the tree. This is the
refinement that matters once sources nest (as Notion pages do, arbitrarily deep):
"which document is the domain?" has no clean answer, but "where does this note sit
in the tree?" always does. Notion's nesting is a *gift* here — it's a
human-curated, multi-level domain tree you inherit for free as each source's
`path` (`Career/Job Search/Target Role`). **Scale by organizing sources, not
facts.** Adding a domain = a new branch in the tree; no schema change, no migration.

The load-bearing point: **that hierarchy is just a `path` (or `parent_id`) field —
any document or relational store holds it. A graph DB is not what provides it.**
Throwing the whole nested notebook into graph nodes doesn't help either: a tree is
a degenerate graph, recall is still semantic search over node text, and you'd be
back to "the graph is just a store." The nesting solves the domain problem
identically on Postgres or on a graph — so it is *not* a reason to keep the graph.

Three recall modes, all cheap:

- **Scoped** — `WHERE path LIKE 'Career/%'` *alongside* the vector search, at any
  level of the tree (a whole subtree, or one leaf). pgvector combines this prefix
  filter with cosine similarity in one query (no traversal). This is the hard,
  multi-level boundary the nesting buys you.
- **Unscoped** — semantic search across everything; a job query won't drag in
  health facts because they're not semantically near. **The embedding space is
  itself a soft domain boundary** — the thing graph-thinking overlooks.
- **Throughput** — pgvector + HNSW handles millions of vectors; thousands across
  dozens of domains is nothing. The scale cliff was never vector count, it's
  recall *precision* as the corpus grows — which the scoped filter addresses.

**The one honest tradeoff — and the only genuine case for a graph here:**
*non-hierarchical cross-links.* The `path` tree captures containment, but not
sideways links across branches — Notion *relations* and *backlinks*, where page A
references page B in a different domain. Flat facts make those implicit (the LLM
reconstructs them at read time from co-retrieved facts) rather than stored,
traversable edges. That's fine for an LLM consumer that already synthesizes. The
test for whether a graph earns its keep: **do you actually traverse those
backlinks** ("show everything connected to Project X, wherever it lives") **, or do
they just exist?** If you only need light cross-linking, a join/link table in
Postgres covers it; reach for a real graph DB only if that traversal gets deep and
central — and even then it's a *relationship-query feature, separate from recall*.

Net: keep the *structure* (the nesting tree solves domains, multi-level, for
free), drop the *graph* (a `path` field provides that structure; the graph
doesn't). The model becomes "nested sources carrying their Notion `path`; facts
optionally derived; recall semantic, scoped by path prefix." The hierarchy is more
legible to a human than graph communities — and it's the same `path` whether the
backend is Postgres or a graph, which is exactly why it isn't an argument *for* the
graph.

---

## Tech stack (the build)

Most of today's stack survives — this swaps the storage layer and a little glue,
not the whole service. **Chosen lean (Steve confirmed 2026-05-31):** Postgres +
pgvector, self-hosted on the VPS, DIY pipeline, keep distillation, embedder
pluggable. Forks stay noted; the recommended path is marked ★.

| Layer | Pick (★) | Notes / alternatives |
|---|---|---|
| Store | ★ **Postgres 16 + pgvector** | One engine: relational (sources/chunks + `path`), vectors (HNSW), full-text (`tsvector`). Alt: SQLite + sqlite-vec + FTS5 (single-file, personal/local-first); Mongo + Atlas (loses SQL joins + `path LIKE`). |
| Hosting | ★ **Self-host on VPS** (`pgvector/pgvector:pg16`) | Fits existing VPS + install/upgrade tooling; most control + learning. One alt worth weighing: **Supabase** — auth + RLS + auto-API hand you the human-edit surface nearly free (PWA writes source rows directly). |
| Embeddings | **Pluggable** — Voyage today | Swap to OpenAI `text-embedding-3` or local (`bge`/`nomic` via Ollama / HF TEI). Orthogonal to the store. Embedding **dim must match the column** (`voyage-3`=1024, `text-embedding-3-small`=1536). |
| Write-time LLM | **Optional** — section cleanup only | No fact-extraction/schema step anymore. Splitting into sections is string work; an optional Claude `decompose()` can clean each section into faithful prose, or skip it and store sections raw. |
| Service | ★ **Python + asyncpg** | Alembic migrations; RRF fusion ~20 lines app-side; FastAPI. (SQLAlchemy 2.0 + `pgvector` pkg if you prefer an ORM.) |
| Ingest | **Notion migrator** | Now writes rows + **computes each page's `path` from the parent chain** — the one new bit of ingest logic; it captures the domain tree. |
| Surface | **PWA** | Thin proxy as today; or direct-to-DB doc editing if Supabase. |

### Concrete schema (DDL)

```sql
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector >= 0.7 for HNSW

CREATE TABLE sources (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind       text NOT NULL,                        -- 'doc' | 'capture' | 'notion_page'
    title      text,
    raw_text   text NOT NULL,                        -- canonical, human-edited content
    parent_id  uuid REFERENCES sources(id) ON DELETE CASCADE,
    path       text NOT NULL DEFAULT '',             -- materialized ancestry: 'Career/Job Search/Target Role'
    version    integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunks (                                -- one row per SECTION of a source (not a schema-tagged "fact")
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id  uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,  -- cascade = wipe-replace for free
    heading    text,                                 -- the section heading ('Location', 'Target Verticals', …)
    text       text NOT NULL,                        -- the section body, self-contained — meaning lives here
    position   integer NOT NULL,                     -- order within the source, for profile() assembly
    embedding  vector(1024) NOT NULL,                -- match the embedder's dim
    created_at timestamptz NOT NULL DEFAULT now(),
    fts        tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(heading,'') || ' ' || text)) STORED
);
-- NO polarity / strength / typed schema: the consumer is an LLM; it reads
-- "avoids fintech — hard dealbreaker" straight from the section text.

CREATE INDEX chunks_embedding_hnsw ON chunks  USING hnsw (embedding vector_cosine_ops);  -- semantic
CREATE INDEX chunks_fts_gin        ON chunks  USING gin  (fts);                           -- lexical (BM25-ish)
CREATE INDEX sources_path_prefix   ON sources (path text_pattern_ops);                    -- domain scope (LIKE 'X/%')
CREATE INDEX chunks_source_pos     ON chunks  (source_id, position);                      -- wipe-replace + ordered profile() dump

-- History (optional): on edit, snapshot OLD raw_text into doc_versions before
-- overwriting — audit trail at the legible doc level.
-- CREATE TABLE doc_versions (source_id uuid, version int, raw_text text, archived_at timestamptz);
```

Three decisions are visible right in the DDL: **`ON DELETE CASCADE`** makes
wipe-replace a one-liner (`DELETE FROM chunks WHERE source_id=$x`); **there is no
`invalid_at`** (bi-temporal invalidation is gone — re-derivation guarantees
currency); and **there is no polarity/strength/typed schema** — a row is just a
section of text, because the consumer is an LLM that reads structure from prose, not
columns. (See *Brain ↔ consumer interface* for why this also simplifies the reads.)

### Pipeline shape — capture, edit, recall (~200 lines)

The whole substrate. `embed()`, `extract()`, `decompose()` are the
storage-agnostic LLM/embedding pieces carried over unchanged from today;
everything else is this one file.

```python
# brain/store.py — the document substrate. asyncpg + an embedder + an extractor.
from dataclasses import dataclass

# ---- ingest: capture, edit, and re-ingest are ALL one operation ----------------

async def upsert_source(db, *, kind, title, raw_text, parent_id=None, id=None) -> str:
    """Create or replace a source, recompute its path, re-derive its facts.
    New capture, a human edit in the PWA, and Notion re-sync are the same call."""
    path = await _compute_path(db, parent_id, title)
    src_id = await db.fetchval("""
        INSERT INTO sources (id, kind, title, raw_text, parent_id, path)
        VALUES (COALESCE($1, gen_random_uuid()), $2, $3, $4, $5, $6)
        ON CONFLICT (id) DO UPDATE
          SET raw_text=$4, title=$3, path=$6,
              version=sources.version+1, updated_at=now()
        RETURNING id
    """, id, kind, title, raw_text, parent_id, path)
    await _rechunk(db, src_id, raw_text)              # <-- wipe-replace lives here
    return src_id

async def _rechunk(db, src_id, raw_text):
    """Wipe-replace core: drop this source's chunks, re-split into sections, re-insert.
    No fact-extraction LLM, no schema — chunks are the doc's own sections, and each
    must stand on its own when it surfaces alone in search."""
    await db.execute("DELETE FROM chunks WHERE source_id=$1", src_id)  # currency by construction
    sections = _split_sections(raw_text)               # [(heading, body)] — see below
    if not sections:
        return
    embs = await embed([f"{h}\n{b}" for h, b in sections])   # batch embed (heading adds context)
    await db.executemany("""
        INSERT INTO chunks (source_id, heading, text, position, embedding)
        VALUES ($1, $2, $3, $4, $5)
    """, [(src_id, h, b, i, e) for i, ((h, b), e) in enumerate(zip(sections, embs))])

def _split_sections(raw_text):
    """Split markdown into self-contained sections by heading (#/##/###); content
    before the first heading is its own chunk; sub-split a section only if it sprawls
    past the budget. Pure string work — an optional decompose() LLM can clean each
    section into faithful prose, but there is no schema-tagging step."""
    ...

async def _compute_path(db, parent_id, title):
    if parent_id is None:
        return title or ""
    parent = await db.fetchrow("SELECT path FROM sources WHERE id=$1", parent_id)
    return f"{parent['path']}/{title}".strip("/")

# ---- recall (Mode 1): targeted retrieval — hybrid semantic + lexical, path-scoped

@dataclass
class Chunk:
    heading: str; text: str; score: float; path: str   # self-contained; LLM reads meaning from text

async def recall(db, query, *, scope=None, k=12) -> list[Chunk]:
    """'Look something up.' Top-k sections matching the query, optionally in a subtree."""
    q_emb      = (await embed([query]))[0]
    scope_like = f"{scope}%" if scope else "%"          # 'Career/%' or match-all
    sem = await db.fetch("""
        SELECT c.id, c.heading, c.text, s.path,
               row_number() OVER (ORDER BY c.embedding <=> $1) AS rank
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE s.path LIKE $3
        ORDER BY c.embedding <=> $1 LIMIT 50
    """, q_emb, query, scope_like)
    lex = await db.fetch("""
        SELECT c.id, c.heading, c.text, s.path,
               row_number() OVER (ORDER BY ts_rank(c.fts, plainto_tsquery('english',$2)) DESC) AS rank
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE c.fts @@ plainto_tsquery('english',$2) AND s.path LIKE $3
        LIMIT 50
    """, q_emb, query, scope_like)
    return _rrf(sem, lex)[:k]

def _rrf(*rankings, c=60):
    """Reciprocal Rank Fusion — reproduces graphiti's COMBINED_HYBRID_SEARCH_RRF."""
    score, row = {}, {}
    for ranking in rankings:
        for r in ranking:
            score[r["id"]] = score.get(r["id"], 0) + 1.0 / (c + r["rank"])
            row[r["id"]]   = r
    order = sorted(score, key=score.get, reverse=True)
    return [Chunk(row[i]["heading"], row[i]["text"], score[i], row[i]["path"]) for i in order]

# ---- profile (Mode 2): domain dump — scout's primary call ----------------------

@dataclass
class Context:
    text: str; sources: list; truncated: bool           # the reusable contract every app codes against

async def profile(db, scope, *, budget=20_000, focus=None) -> Context:
    """'Give me everything about this domain,' assembled. Completeness, not precision
    — a scoped dump can't miss a dealbreaker the way query-recall can."""
    rows = await db.fetch("""
        SELECT s.path, s.title, c.heading, c.text, c.position
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE s.path LIKE $1
        ORDER BY s.path, c.position
    """, f"{scope}%")
    bundle = _assemble(rows)                             # rebuild the subtree as structured markdown
    if _tok(bundle) <= budget:                           # common case: the slice fits — return it whole
        return Context(bundle, _provenance(rows), truncated=False)
    focused = await recall(db, focus or scope, scope=scope, k=40)    # too big → degrade to recall-in-scope
    return Context(_assemble_chunks(focused), _provenance(rows), truncated=True)  # …and SAY it was cut

# _assemble / _tok / _provenance are trivial: group rows into '# path / ## title /
# ### heading' markdown; count tokens; list source paths+ids for citation.
```

The shape in one breath: **ingest is one function** (capture = edit = re-sync, now
just splitting the doc into its own sections — no extraction LLM, no schema), and
the brain exposes **two reads** — `recall(query)` for lookups, `profile(scope)` for
domain dumps. The hard parts graphiti owned are *gone* (invalidation) or never
needed (the polarity/strength schema — an LLM reads that from the text). With error
handling, batching, and a pool this stays well under 200 lines — small enough to
own, which graphiti and Mem0 are not.

---

## RAG: what we'd be experimenting with

A primary reason this project exists is hands-on **RAG experimentation.** This
refactor *serves that goal better than the graph does* — which resolves the main
worry about leaving the graph behind.

**The reframe:** the current graph setup is a black-box GraphRAG / knowledge-graph-
memory variant — graphiti owns the whole retrieval pipeline and you configure it
from outside. The pgvector architecture is **textbook RAG with the hood open**: you
build, tune, and *evaluate* the retrieval pipeline yourself. You've been doing RAG
all along (graph-flavored); this moves you to its canonical core.

**What moves from black-box to your hands** — every "you own" row is a RAG
experiment the current setup won't let you run:

| RAG component | Today (graphiti, hidden) | Document / pgvector (you own) |
|---|---|---|
| Chunking / what to embed | embeds extracted edges | raw chunks vs distilled propositions |
| Embedding model & dim | a config value | wired directly, swappable, dim-aware |
| ANN index & params | managed by the engine | tune HNSW (`m`, `ef_search`) |
| Semantic query | abstracted | the `<=>` cosine query in `recall()` |
| Lexical / BM25 | internal | `tsvector` FTS you build |
| Hybrid fusion (RRF) | a flag (`COMBINED_HYBRID_SEARCH_RRF`) | `_rrf()` you implement + tune `c` |
| Reranking | limited | add a cross-encoder / Voyage rerank pass |
| Retrieval eval | bolt-on | own recall@k end-to-end |
| Query transforms | no hook | HyDE / multi-query |

The `recall()` + `_rrf()` in the Tech stack skeleton are literally the canonical
RAG retrieval step, hand-written. (Repo's `../docs/rag-primer.md` is the theory;
this is where those concepts become knobs.)

**Flavor choice — itself a RAG experiment.** Keeping distillation = *proposition-
based retrieval* (embed distilled facts, a more sophisticated variant); dropping it
= *raw-RAG* (chunk + embed, the vanilla, most-textbook form). Both are RAG; it's a
knob, not a question of whether this "counts."

**What we leave behind, and why it's fine.** Graph-native retrieval — multi-hop
traversal, GraphRAG community summarization. Real and interesting, but unused today
(star topology, node-distance rerank disabled), so no experiment we're actually
running is lost. **Decision (2026-05-31): leaving graph-DB experimentation behind
is accepted**, now that its only real benefit here (dedup + bi-temporal, not
relationships) is understood.

**Concrete RAG experiments this unlocks** (rough backlog):

1. **Reranker pass** — add Voyage rerank or a cross-encoder after RRF; measure
   recall@k lift.
2. **Chunk vs proposition** — embed raw chunks vs distilled facts; compare
   retrieval precision and answer faithfulness.
3. **HNSW tuning** — `m` / `ef_construction` / `ef_search` vs recall/latency.
4. **Hybrid weighting** — RRF `c`, semantic-vs-lexical balance, MMR for diversity.
5. **Retrieval-eval scorecard** — a recall@k / precision harness (the LongMemEval
   idea from the Supermemory-patterns notes); the real RAG skill, and the thing
   that tells you whether any of 1–4 actually helped.
6. **Query transforms** — HyDE, multi-query expansion; measured on the same
   scorecard.

---

## Does a turnkey product exist? (landscape, May 2026)

The reason the answer is clean: graphiti and the vector-first products run the
**same LLM pipeline** (extract → embed → dedup → retrieve). They differ only in
(a) backend and (b) how rigorously they handle "this fact replaced that one."

- **Mem0** — closest "graphiti pointed at a vector store." Extraction + dedup +
  retrieval as a managed layer; **pgvector-native** (also Qdrant/Chroma/Milvus/
  Redis); graph optional & parallel, not the spine. *Weak spot:* temporal/
  contradiction — base config can surface a stale fact if it's semantically
  closer than the update. That's exactly graphiti's strength and our `invalid_at`
  logic — and exactly the part the wipe-replace model engineers away.
- **Supermemory** — single API doing extraction + profile + **contradiction
  resolution + selective forgetting**; closed-source, enterprise self-host.
- **Cognee** — open-source, local-first, multi-backend (vector + graph +
  relational).
- **Zep** — the commercial product *built on graphiti*; not an alternative, it's
  the managed version of what we already have.

**Likely verdict: DIY-on-pgvector beats adopting Mem0 here**, because Mem0's main
value (managed dedup/temporal) is the part the source-of-truth model removes, and
we'd still fight a black box on the edit-surface requirement. The thing we'd own
instead — extract call + similarity query + cascade delete — is small enough to
debug, and a nice standalone project piece.

(Sources: vectorize.io Mem0-vs-Zep & best-memory-systems-2026; deepwiki mem0;
atlan mem0-alternatives; graphlit memory-framework survey; supermemory blog.)

---

## Versus the "Claude + Obsidian" second brain

The buzzy alternative — point Claude at an Obsidian vault through an MCP server and
let a large context window do the rest — is part of the motivation for this
project, so it's worth being clear-eyed. The two aren't the same category:
**Obsidian + Claude is a turnkey consumer setup; this is retrieval
infrastructure.** They optimize for different things, and they're *converging*.

| Dimension | Claude + Obsidian (agentic read) | Brainbot (pgvector RAG) |
|---|---|---|
| **Retrieval** | agentic — filename/grep search, then read whole notes; big context covers it | precomputed hybrid (semantic + BM25 + RRF) → compact top-k |
| **Consumption model** | interactive, human-in-the-loop, client-bound (a person at a Claude client, machine on) | always-on headless service; apps (scout, cron, agents) hit `recall()` 24/7, no human present |
| **Auto-update** | manual — you edit notes; no scheduled ingest of external sources | scheduled sync (e.g. Notion API on `last_edited_time`) keeps the brain current on its own |
| **Faithfulness** | high — reads intact notes with full surrounding context | risk — distilled facts can drop nuance/negatives (LEARNINGS Ch.3); mitigate with provenance or raw-RAG |
| **Semantic recall** | lexical: grep misses synonyms/paraphrase unless a vector plugin is added | embeddings catch conceptually-related content regardless of wording |
| **Scale** | great at personal scale; degrades as the vault → tens of thousands (can't read all; keyword misses) | sub-linear search; scales to huge corpora — RAG's home turf |
| **Cost / latency per query** | high — stuffs many full notes into context | low — small top-k |
| **Editing / freshness** | edit a file = instantly live, zero reindex; Obsidian *is* the edit surface | edit → re-extract → re-embed (wipe-replace); an index step exists |
| **Cross-note links** | human-curated wikilinks/backlinks = a real, meaningful knowledge graph the model can follow | flat facts; cross-domain links implicit |
| **What you learn** | prompt/agent design + MCP — *not* RAG internals | the RAG pipeline itself (this project's whole point) |
| **Product potential** | single-user personal workflow | generic, multi-user retrieval infra / API |
| **Build effort** | ~zero (install MCP, point at vault) | real (pipeline, schema, eval) |

**Honest verdict.** For an *effortless personal second brain today*, Obsidian +
Claude probably wins — faithful whole-note reads, zero build, edit-in-place,
human-curated links, and a big context window already covers personal scale. The
buzz is earned. Brainbot wins on the axes that are *actually the goals here*:
**learning RAG, cheap/fast per-query retrieval, scaling past one person, and
product-grade infrastructure.** No contradiction — different optimization targets.
Note the irony: Obsidian's backlinks give you the one genuine "graph" benefit (real
human-authored cross-links) the graph DB never did — because they're curated, not
LLM-extracted.

**The trend worth naming.** As context windows grow and models get better at
tool-use, agentic-read is a genuine challenger to RAG for *personal-scale* corpora;
RAG's zone of necessity is shrinking toward large-scale / cost- / latency-sensitive
cases. So building RAG here is justified by **learning + scale/product ambition**,
not by "it beats Obsidian for my notes today." Keeping that honest keeps the
project honestly motivated.

**The synthesis (not either/or).** These are different *layers*: Obsidian owns
storage + editing; RAG owns retrieval + serving. The source-of-truth model already
mirrors Obsidian's "edit the doc" philosophy — so the endgame could **use an
Obsidian vault as the human edit surface and `sources` content, with this pipeline
as the retrieval/serving layer for agents.** That takes the buzz seriously without
giving up the RAG learning or the product infra. It's the natural generalization of
"Notion is the first migrator" — Obsidian is just another source.

---

## Why a service, not a workflow

The sharpest product differentiator vs Claude + Obsidian isn't the substrate or the
retrieval method — it's the **consumption model**, an axis orthogonal to everything
above. *Who consumes the brain, and when?*

- **Claude + Obsidian** = pull, interactive, **human-in-the-loop, client-bound.** A
  person sits at a Claude client, on a machine that's on, and asks. Nothing happens
  when they're away. A human using an AI to browse their notes — a *workflow*.
- **Brainbot** = **always-on, headless, machine-in-the-loop.** A `recall()` endpoint
  that scout, a cron job, or a future agent hits at 3am — no human, no desktop
  client — and gets current intelligence. A *service*.

Litmus scenario: *scout, running server-side at 3am, needs the user's job
preferences.* Obsidian + Claude has no answer (laptop asleep, no session open); this
is the exact thing brainbot exists to serve. It's the "out of sight, out of mind —
my apps just work off it" promise, made concrete.

**Orthogonal to substrate.** Storage and consumption are independent choices — you
could put a service in front of markdown files, or query Postgres interactively. To
get always-on, service-grade integration over Obsidian you'd have to host the vault
and build a retrieval service over it… which is *this project with markdown as the
store.* Obsidian doesn't give you the service layer; you'd build it regardless.

**Auto-update is the other half — and Notion fits it where Obsidian can't.** "Always
working off current intelligence" needs the brain to *refresh itself*, not just
serve. The source decides whether that's possible headlessly:

- **Obsidian** — local, app-bound files; no cloud API to pull from without a machine
  running the app. Not a natural auto-sync source.
- **Notion** — cloud-hosted with a first-class public API; content is reachable
  programmatically, always, no local machine involved. The natural auto-sync source.
  Sync design: incremental pull on each page's `last_edited_time` → re-ingest only
  changed pages (the wipe-replace-per-source op); walk the parent chain to set each
  source's `path` (the domain tree, for free); walk the block tree for clean text;
  respect rate limits (~a few req/s) and paginate. Webhooks may allow push where
  supported, but polling on `last_edited_time` is the dependable baseline.

**The synthesis.** Because consumption is orthogonal to substrate, the endgame is
*both*: an Obsidian vault or Notion as the **human edit surface + source**, brainbot
as the **headless service** that indexes it and serves machines. Obsidian/Notion for
humans; brainbot for apps — Obsidian becomes "just another migrator," like Notion.

**The honest cost.** "Apps consume it automatically" is paid for by *operating
infrastructure* — a Postgres service, a scheduled sync worker, uptime, the ingest
pipeline. Obsidian + Claude is near-zero-ops (it's just a laptop). The trade —
zero-ops personal tool → run a small service so your apps get current intelligence
for free — is right for a product with consumers like scout, and overkill for a solo
note-reader. Which is, once more, why the two setups don't really compete.

---

## Brain ↔ consumer interface (a reusable intelligence library)

> **CORRECTION (2026-05-31) — read this first; it supersedes the "two core reads +
> discovery read" framing below.** The principle that settles the interface:
> **downstream apps are dumb — they only ever know what the brain gives them.** So
> any call that requires the caller to know a *scope* (a path) is, by definition,
> **not a consumer call** — it leaks the brain's internal taxonomy into the consumer.
> That kicks **both `profile(scope)` and `map(scope)` out of the consumer contract.**
> (The earlier idea that a consumer would *discover* its scope via `map` was wrong —
> dropped.)
>
> **There are three audiences, not two:**
> - **Dumb consumer apps (scout, …):** the entire contract is **`recall(query)`** —
>   ask a question, get the relevant chunks. No scope, ever. Completeness (don't miss
>   a dealbreaker when gating) is served *query-side* — `recall` in a "return
>   everything related" mode (relevance threshold / high `k`) — never by `profile`.
> - **The brain itself (internal jobs):** uses `map`/`profile` as *machinery*.
>   `map` powers **sync reconciliation** (diff the Notion tree vs the brain's
>   inventory) and maintenance (re-embed, dedup, GC). `profile` is the brain's
>   **self-enrichment** primitive: a job assembles a domain (`profile('Job Hunting')`)
>   → an LLM distills a high-signal **digest** stored as a derived source → `recall`
>   surfaces it. *This recreates the old `profile()`'s "here's the user" value — built
>   by the brain from the docs, delivered through `recall`, with the consumer never
>   knowing a scope existed.* Also: contradiction sweeps, cross-domain link mining.
> - **The owner (you, via the authed PWA/admin):** `map`/`profile` + edit, because
>   you legitimately know your own folders.
>
> Net: **`recall(query)` is the whole public/consumer surface.** `profile`/`map` are
> internal + owner tools, not consumer endpoints. The sections below describe `recall`
> correctly; treat their "profile = scout's primary mode" / "map = consumer discovery"
> claims as superseded by this block.

The brain isn't scout's sidecar — it's a **reusable intelligence-gathering library**
that any personal app consumes; scout is just the first. So the interface is kept
small, domain-agnostic, and consumer-agnostic — and **read-only for consumers**
(writes only ever come from sources; see the boundary below). **Two core reads, plus
a discovery read:**

- **`recall(query, scope=None)` — targeted retrieval ("look something up").** Hybrid
  semantic + lexical search; returns the top-k sections matching a query, optionally
  within a path subtree. For ad-hoc questions and when the brain is large.
- **`profile(scope)` — domain dump ("give me everything about this domain"),
  assembled.** Returns the *whole* relevant slice — every section under `scope`,
  rebuilt into a structured context bundle. For bounded assessment tasks where
  *completeness beats precision.*
- **`map(scope=None)` — domain discovery (the source tree).** Returns the
  `path`/title tree (`SELECT path, title FROM sources WHERE path LIKE $1 ORDER BY
  path`) so a consumer that doesn't already know its scope can find it. This is the
  "if the right domain isn't obvious, a source-tree layer covers the gap" piece.

**Why two, and why the split matters.** scout's job is gating (green/yellow/red),
and for gating the worst failure is *missing* a fact — miss "avoids fintech" and you
green-light a fintech company. Query-recall can miss (search whiffs, or the consumer
doesn't think to ask). A scoped `profile()` dump can't: it hands over the entire
domain, so the dealbreaker is present whether or not anyone "asked." And a domain
profile is small (the Target role doc is ~600 words), so it fits in context. So
**`profile(scope)` is scout's primary call; `recall` is the ad-hoc / large-brain
fallback** — including recall *within* a scope when one domain grows too big to dump.

This is the librarian/decider split, extended: the brain (librarian) owns retrieval
**and assembly**; the consumer (scout, decider) owns reasoning. Assembly belongs in
the library so every app gets well-formed context for free instead of re-deriving it.

### Constructing the domain dump (`profile`)

More than `SELECT … WHERE path LIKE`. The design:

1. **Gather + order.** Pull every chunk under the scope, ordered by `(path,
   position)`, so the human's structure survives.
2. **Re-assemble as a mini-document.** Render the subtree back into structured
   markdown — `# Job Hunting / ## Target role / ### Location …` — not a flat soup.
   The consumer LLM gets the same shape the human authored, with provenance.
3. **Budget + degrade gracefully.** If the slice fits the token budget, return it
   whole (the common, safe case). If not, *don't silently truncate* — degrade to
   `recall`-within-scope (or summarize) and **flag `truncated=True`** with what was
   dropped. (No silent caps.)
4. **Provenance.** Return source paths/ids alongside the text, so the consumer can
   cite "per your Target role doc."
5. **Fresh for free.** Source-of-truth + wipe-replace keeps the dump current and
   non-redundant — which is *what makes "just dump the slice" safe.* A stale or
   duplicate-ridden store would make dumping a liability.
6. **Cacheable later.** A domain's assembled bundle can be cached, invalidated on any
   source change under the scope — an optimization, not v1.

### The reusable contract

Both calls return one type — the thing every app codes against:

```
Context { text:      str   # assembled, structured markdown
          sources:   list  # provenance: (path, source_id, last_edited)
          truncated: bool  # was the slice cut to fit budget? }
```

Delivered as the **service API** (`GET /recall?q=&scope=`, `GET /profile?scope=`)
for cross-app, cross-language use (scout can be TS while the brain is Python), plus a
thin client SDK per language wrapping the two calls. *This* is what makes it a
library, not a scout feature — a new personal app gets "current, assembled
intelligence about domain X" in one call and never touches pgvector, paths,
chunking, or budgets.

**What this does *not* require: a redesign.** You already have `recall` and
`profile`; the deltas are (1) add a `scope` path-prefix to `profile`, (2) assemble +
budget the dump instead of dumping raw, (3) return sections not schema-tagged facts,
(4) point consumers at `profile(scope)` by default. The bigger shift is the mental
model — *consumers pull a scoped context bundle; they don't hold a Q&A.*

### Fit check & the multi-consumer roadmap

**Does this hold the librarian/analyst line?** Yes — more cleanly than before. The
brain returns *raw, faithful content, never a verdict*; all interpretation — gates
(OR/AND), dedup, ranking, presentation — is the consumer's job (the validated
Phase-1 consumer boundary). Dropping the polarity/strength schema was the purifying
move: the librarian stopped pre-judging "hard vs soft" (an analyst's call). Assembly
in `profile` stays librarian work (gather + arrange, not interpret) **as long as
ingest stays faithful** — store the human's section text, don't let a rewrite
editorialize. (Completeness is conditional, too: `profile` can't-miss only while the
slice fits budget; past that it degrades to recall-in-scope and flags `truncated` —
the librarian says "couldn't hand you everything," the analyst decides what to do.)

**Read-only boundary (decided).** Consumers **never write back** to the brain. Writes
come only from sources (Notion sync, captures). A consumer's takeaways don't mutate
the brain — if something should be remembered, it enters as a *source*, through the
human. This keeps the librarian pure and the source-of-truth model intact.

**Multi-consumer pattern.** Because the interface carries no consumer-specific
concepts, every app is the same shape — *pick a scope or query → get a `Context` →
do its own job*:

| Consumer app | Brain call | Its job (the analyst part) |
|---|---|---|
| scout | `profile('…/Job Hunting')` | gate companies green/yellow/red |
| cover-letter drafter | `profile('…/Job Hunting')` + company | write the letter |
| meeting prep | `recall('person X', scope='People')` | brief you |
| learning planner | `profile('Career')` | suggest next skills |
| personal chatbot | `recall(question)` | answer ad-hoc |

**Interface roadmap (phased).**
- **Phase 1:** `recall(query, scope)` + `profile(scope)` + `map(scope)` (discovery).
- **Later phase (planned, not Phase 1): multi-scope assembly** — one call that
  assembles several domains at once (Job Hunting + People + Projects) into a single
  budgeted `Context`. Composable today via repeated `profile`; promote to first-class
  when a consumer needs it.

---

## Embeddings note

**Storage and embedding are orthogonal.** pgvector *stores and searches* vectors;
it does not *make* them. An embedder is needed regardless of backend (graph or
document). Options: keep **Voyage** (current), switch to **OpenAI
`text-embedding-3-*`**, or **self-host** (`bge` / `e5` / `nomic-embed-text` via
sentence-transformers or Ollama — free, private, run the compute). Mem0 also needs
an embedder configured; it doesn't remove the decision, just wraps it.

---

## When to actually pull the trigger

Don't migrate on aesthetics. Re-open the substrate question when **one** of these
forces it:

1. The **human-edit requirement** becomes load-bearing (curating the brain by
   hand is needed, not nice-to-have).
2. **Recall quality plateaus** and inspecting/editing facts by hand is the only
   way forward.

The real migration cost isn't the code — it's **re-validating recall quality on
real data** and **re-earning dedup behavior** (both survive `git revert` poorly).
Until a forcing function hits, graphiti's dedup is doing quiet real work, and
that's a fine reason to leave it.

---

## Open questions / sharp edges

- **Closed-set legibility** (carried over from the earlier graph design): "allowed
  verticals are *exactly* these four" must survive as a set, not shatter into
  disconnected likes. How does that survive flat-fact extraction + read-time
  dedup?
- **Dedup tuning** (if we ever go global-merged): merge thresholds that don't
  over-merge (the README already notes graphiti over-merges sometimes) or
  under-merge. Iterative, not hard, but real.
- **Section-aware re-extract**: wipe-replace per whole doc is correct but coarse.
  Diff-and-only-re-extract-changed-sections is a later optimization — do NOT do
  it for v1; full re-extract per edited doc is cheap and simplest.
- **Migration path** from the current FalkorDB/graphiti store to pgvector if this
  is ever adopted (re-ingest from source docs is the clean path — and re-ingest
  *is* the model, so there's natural alignment).

---

## Future limits of `recall` (when it outgrows its job)

`recall(query)` answers exactly one thing: *find the content relevant to this
question.* It stays adequate until a question needs something retrieval
fundamentally can't do — **aggregate, compose, synthesize, time-travel, or
traverse.** Roughly in the order they'd bite, with the successor each needs:

1. **Exhaustive / aggregate** ("list *every* X", "how many?") — top-k ranks by
   similarity; it doesn't enumerate-with-guarantee or count. **The first real wall.**
   Successor: a *structured* query path (SQL-ish filters over fields/metadata), not
   semantic search.
2. **Scale-precision decay** — at tens of thousands of chunks the embedding space
   crowds and top-k gets noisy. Not a break, an *augment*: a reranker pass, metadata
   filters, hierarchical retrieval.
3. **Multi-constraint composition** ("Series A *and* remote *and* a vertical I
   like") — one shot can't JOIN constraints. Solved *above* recall: the consumer runs
   several recalls (agentic retrieval) or structured filters. Not a brain change.
4. **Whole-picture synthesis** ("summarize who I am professionally") — recall returns
   fragments, not a coherent whole. Solved *beside* recall: the brain-side enrichment
   loop (`profile` → digest) pre-synthesizes, and recall surfaces the digest.
5. **Temporal / "what changed"** — wipe-replace keeps only the present. Successor:
   doc-version history (versioning the source, git-style) — deferred by design.
6. **Relationship / multi-hop traversal** ("how does X connect to Y across domains")
   — flat chunks + similarity can't traverse. Successor: a relationship/graph layer —
   the one genuine graph case, full circle.

**Synthesis:** `recall` never goes *wholesale* useless — specific *question shapes*
outgrow it, and each successor has a known slot (structured queries, rerankers,
brain-side digests, doc-versions, a relationship layer). For a single-user personal
brain answering "find me the relevant stuff" questions, it's plenty for the
foreseeable future; the first to bite are aggregate queries and scale-precision, both
*augmentations*, not replacements.
