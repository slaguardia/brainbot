# Memory model

> **Historical (graph design).** Describes the earlier graphiti-over-FalkorDB
> build. The **live backend is now Postgres + pgvector** — sources split into
> embedded chunks, no graph, no extraction LLM. See
> [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md) and
> [`../plans/document-substrate-exploration.md`](../plans/document-substrate-exploration.md).

Brainbot stores memory as an **episode-shaped graph**: entities, edges, and bi-temporal facts. Not a turn-shaped vector store of chat history.

## How it works

Every write is an *episode* — a chunk of text from a capture, a chat turn, a migrated note. An LLM extracts entities and edges from the episode and merges them into the graph. Facts are bi-temporal: each edge carries both the time it was true in the world and the time the system learned about it. Corrections invalidate old facts cleanly instead of letting them rot in place.

Queries are graph traversals. "What people have I talked to about X in the last 30 days, and what did each of them say?" is a structured query, not a vector search.

## Why graph, not turn-shaped

The turn-shaped alternative — strings plus embeddings, semantic recall per chat turn (the [Hermes Agent](https://github.com/nousresearch/hermes-agent) shape) — would ship ~70% of the surface in an afternoon. We picked graph anyway because:

- Structured queries over your own life are worth the extraction cost on every write.
- Bi-temporal handling means corrections work. In a turn-shaped store, an old wrong fact stays in the embedding space and keeps surfacing.
- The graph is editable by a human (see [human-edit-surface.md](./human-edit-surface.md)) in a way a vector blob isn't.

## The honest cost

Extraction is ~$0.0016 per write at Haiku rates and 1–3s of latency per episode. The graph fragments brittlely if extraction drifts. Three hedges keep it viable:

1. Hybrid retrieval (graph traversal + BM25 + embeddings — see [embedder.md](./embedder.md)).
2. The human-edit surface in the PWA.
3. A weekly dedup audit.

## Fallback if extraction quality fails

Add a vector layer alongside the graph (Phase 4 backlog). Not a defeat — an admission that some recall is better as semantic search.

## Alternatives considered

- **Turn-shaped vector store (Hermes-like).** Cheaper, simpler, ships faster. Rejected for the reasons above. Comparison table in [architecture.md](../architecture.md#why-not-just-use-hermes-or-similar).
