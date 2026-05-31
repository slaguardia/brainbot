# Plan: Document substrate (source-of-truth docs + derived facts on pgvector)

## Status: exploratory — NOT committed

Captured 2026-05-31 from a design conversation. Steve is questioning whether
the graph DB earns its keep and is **likely leaving the current system as-is for
now** — but this direction looks like the better long-term architecture, so it's
written down to return to. Nothing here is decided. See also
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
sources(id, kind, title, raw_text, domain, version, created_at, updated_at)
facts(id, source_id FK, fact text, fact_embedding vector,
      polarity, strength, valid_at, created_at)
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

**Domain = the source document, or a folder of them. Facts inherit their domain
from `source_id`.** No separate domain abstraction, no per-fact domain tags — the
corpus of sources *is* the partition, the way a filesystem categorizes by folder
rather than tagging every byte. **Scale by organizing sources, not facts.** Adding
a domain = adding a folder; no schema change, no migration.

Three recall modes, all cheap:

- **Scoped** — `WHERE domain = 'career'` *alongside* the vector search. pgvector
  combines a metadata filter with cosine similarity in one query (no traversal).
  This is the hard boundary.
- **Unscoped** — semantic search across everything; a job query won't drag in
  health facts because they're not semantically near. **The embedding space is
  itself a soft domain boundary** — the thing graph-thinking overlooks.
- **Throughput** — pgvector + HNSW handles millions of vectors; thousands across
  dozens of domains is nothing. The scale cliff was never vector count, it's
  recall *precision* as the corpus grows — which the scoped filter addresses.

**The one honest tradeoff** (same as the cross-fact one, at domain scale): flat
facts make **cross-domain relationships implicit** — the LLM reconstructs links
at read time instead of them being stored edges. Fine for an LLM consumer that
already synthesizes. **Revisit a thin relationship layer only if persistent,
queryable cross-domain links become load-bearing** ("show everything across all
domains that constrains my job search") — not before.

Net: the document model scales *better* on delineation than the graph — folders
are more legible to a human than communities, and they're the same `source_id`
that powers wipe-replace.

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
