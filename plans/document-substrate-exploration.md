# Plan: Document substrate (source-of-truth docs + derived facts on pgvector)

## Status: intended direction — migration not yet triggered

Captured 2026-05-31 from a design conversation, refined over it. Steve now accepts
the graph DB doesn't earn its keep for this use case (its only real benefit here is
dedup + bi-temporal, **not** relationships) and is **fine leaving graph-DB
experimentation behind** — the remaining hesitation (losing RAG learning) is
resolved by the [RAG section](#rag-what-wed-be-experimenting-with): this substrate
is *more* hands-on RAG, not less. So this is increasingly the **intended refactor
direction**, though the migration itself isn't scheduled/triggered yet (see *When
to pull the trigger*). See also
[`graph-as-source-of-truth.md`](graph-as-source-of-truth.md) (the *graph-native*
answer to the same edit/source-of-truth problem) and
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
facts(id, source_id FK, fact text, fact_embedding vector,
      polarity, strength, valid_at, created_at)
-- path = materialized ancestry (e.g. 'Career/Job Search/Target Role'); domain
--   scoping is a prefix match on it. parent_id mirrors the source tree (Notion
--   nesting). See "Scalability" for why this — not a graph — solves domains.
-- entities table optional; only if we want cross-source merge (see fork below)
```

Per-step swap:

- **Capture** → LLM extract facts → embed → `INSERT`. (Same decompose +
  extraction-override prompt we already have.)
- **Recall** → `ORDER BY fact_embedding <=> $q` (semantic) + `to_tsvector` FTS
  (our BM25), fused with RRF in ~20 lines. Reproduces `COMBINED_HYBRID_SEARCH_RRF`.
- **Profile** → `SELECT ... WHERE <live>` — same as today's `invalid_at IS NULL`
  filter, but currency is now guaranteed by construction (see below), so the
  filter may not even be needed.

Notice facts are stored as **flat documents whose text carries the meaning** —
which is *exactly what recall already returns* (`fact` prose + attributes, never
the subject/object nodes). A document store is a more honest representation of
what the brain already does than the graph is.

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
| Store | ★ **Postgres 16 + pgvector** | One engine: relational (sources/facts + `path`), vectors (HNSW), full-text (`tsvector`). Alt: SQLite + sqlite-vec + FTS5 (single-file, personal/local-first); Mongo + Atlas (loses SQL joins + `path LIKE`). |
| Hosting | ★ **Self-host on VPS** (`pgvector/pgvector:pg16`) | Fits existing VPS + install/upgrade tooling; most control + learning. One alt worth weighing: **Supabase** — auth + RLS + auto-API hand you the human-edit surface nearly free (PWA writes source rows directly). |
| Embeddings | **Pluggable** — Voyage today | Swap to OpenAI `text-embedding-3` or local (`bge`/`nomic` via Ollama / HF TEI). Orthogonal to the store. Embedding **dim must match the column** (`voyage-3`=1024, `text-embedding-3-small`=1536). |
| Write-time LLM | ★ **Anthropic Claude** (keep distillation) | decompose + extract, unchanged. Dropping distillation (raw-RAG) removes the LLM from the write path — simpler, noisier recall. |
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

CREATE TABLE facts (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id      uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,  -- cascade = wipe-replace for free
    fact           text NOT NULL,
    fact_embedding vector(1024) NOT NULL,            -- match the embedder's dim
    polarity       text,                             -- 'positive' | 'negative'
    strength       text,                             -- 'hard' | 'soft'
    valid_at       timestamptz,                      -- when the fact became true; NO invalid_at — currency is by construction
    created_at     timestamptz NOT NULL DEFAULT now(),
    fts            tsvector GENERATED ALWAYS AS (to_tsvector('english', fact)) STORED
);

CREATE INDEX facts_embedding_hnsw ON facts USING hnsw (fact_embedding vector_cosine_ops);  -- semantic
CREATE INDEX facts_fts_gin        ON facts USING gin  (fts);                                -- lexical (BM25-ish)
CREATE INDEX sources_path_prefix  ON sources (path text_pattern_ops);                       -- domain scope (LIKE 'X/%')
CREATE INDEX facts_source_id      ON facts (source_id);                                     -- wipe-replace + joins

-- History (optional): on edit, snapshot OLD raw_text into doc_versions before
-- overwriting — audit trail at the legible doc level, not in the facts.
-- CREATE TABLE doc_versions (source_id uuid, version int, raw_text text, archived_at timestamptz);
```

Two decisions are visible right in the DDL: **`ON DELETE CASCADE`** makes
wipe-replace a one-liner (`DELETE FROM facts WHERE source_id=$x`), and **there is
no `invalid_at`** — the column graphiti needs for bi-temporal invalidation is
simply gone, because re-derivation guarantees currency.

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
    await _rederive_facts(db, src_id, raw_text)       # <-- wipe-replace lives here
    return src_id

async def _rederive_facts(db, src_id, raw_text):
    """Wipe-replace core: drop this source's facts, re-extract, re-insert."""
    await db.execute("DELETE FROM facts WHERE source_id=$1", src_id)   # currency by construction
    body  = await decompose(raw_text)                 # faithful rewrite (skip for raw-RAG)
    items = await extract(body)                        # -> [{fact, polarity, strength, valid_at}]
    if not items:
        return
    embs = await embed([it["fact"] for it in items])   # batch embed
    await db.executemany("""
        INSERT INTO facts (source_id, fact, fact_embedding, polarity, strength, valid_at)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, [(src_id, it["fact"], e, it.get("polarity"), it.get("strength"), it.get("valid_at"))
          for it, e in zip(items, embs)])

async def _compute_path(db, parent_id, title):
    if parent_id is None:
        return title or ""
    parent = await db.fetchrow("SELECT path FROM sources WHERE id=$1", parent_id)
    return f"{parent['path']}/{title}".strip("/")

# ---- recall: hybrid semantic + lexical, RRF-fused, optional path scope ----------

@dataclass
class Fact:
    fact: str; score: float; polarity: str | None; strength: str | None; path: str

async def recall(db, query, *, scope=None, k=12) -> list[Fact]:
    q_emb      = (await embed([query]))[0]
    scope_like = f"{scope}%" if scope else "%"         # 'Career/%' or match-all
    sem = await db.fetch("""
        SELECT f.id, f.fact, f.polarity, f.strength, s.path,
               row_number() OVER (ORDER BY f.fact_embedding <=> $1) AS rank
        FROM facts f JOIN sources s ON s.id = f.source_id
        WHERE s.path LIKE $3
        ORDER BY f.fact_embedding <=> $1 LIMIT 50
    """, q_emb, query, scope_like)
    lex = await db.fetch("""
        SELECT f.id, f.fact, f.polarity, f.strength, s.path,
               row_number() OVER (ORDER BY ts_rank(f.fts, plainto_tsquery('english',$2)) DESC) AS rank
        FROM facts f JOIN sources s ON s.id = f.source_id
        WHERE f.fts @@ plainto_tsquery('english',$2) AND s.path LIKE $3
        LIMIT 50
    """, q_emb, query, scope_like)
    return _dedupe(_rrf(sem, lex))[:k]

def _rrf(*rankings, c=60):
    """Reciprocal Rank Fusion — reproduces graphiti's COMBINED_HYBRID_SEARCH_RRF."""
    score, row = {}, {}
    for ranking in rankings:
        for r in ranking:
            score[r["id"]] = score.get(r["id"], 0) + 1.0 / (c + r["rank"])
            row[r["id"]]   = r
    order = sorted(score, key=score.get, reverse=True)
    return [Fact(row[i]["fact"], score[i], row[i]["polarity"], row[i]["strength"], row[i]["path"])
            for i in order]

def _dedupe(facts):
    """Per-source model: collapse the same point surfaced from different sources.
    v1 = normalized-text collapse (cheap). Semantic collapse (cosine > 0.92) is a
    refinement — carry the embedding on the row to do it."""
    seen, kept = set(), []
    for f in facts:
        key = " ".join(f.fact.lower().split())
        if key not in seen:
            seen.add(key); kept.append(f)
    return kept

# profile(db, scope=None) is just: SELECT ... FROM facts JOIN sources WHERE path LIKE ...
# (no invalid_at filter needed — every stored fact is current by construction).
```

The shape in one breath: **ingest is one function** (capture = edit = re-sync),
**recall is two queries + RRF + a dedupe pass**, and the hard parts graphiti owns
are either *gone* (invalidation) or *demoted to a cheap read-time pass* (dedup).
With real error handling, batching, and a connection pool this lands around 200
lines — small enough to own and debug, which graphiti and Mem0 are not.

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

- **Closed-set legibility** (carried from `graph-as-source-of-truth.md`): "allowed
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
