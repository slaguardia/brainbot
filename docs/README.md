# Brainbot docs

Working docs for the current implementation. Each file explains how one piece works today and why it's shaped that way.

These are not historical — they describe the system as it is, and get updated when the system changes. If a decision gets reversed, the old version goes away with it. Each doc ends with a brief "alternatives considered" section so the tradeoff is legible without needing a separate history file.

## Start here

- [rag-primer.md](./rag-primer.md) — plain-English primer with analogies: what RAG is, how GraphRAG differs from naive RAG, what all the tool names (LangChain / Pinecone / Neo4j / Graphiti) actually mean, and how brainbot compares to Obsidian. Start here if the field is new to you.
- [how-it-works.md](./how-it-works.md) — end-to-end walkthrough with a worked example: episode in, extraction, storage, retrieval, correction. Read this second to see what Graphiti actually does with a real piece of data.

## Per-component

- [memory-model.md](./memory-model.md) — episode-shaped graph, bi-temporal facts, why not turn-shaped
- [graph-engine.md](./graph-engine.md) — Graphiti: extraction, dedup, storage layer
- [graph-database.md](./graph-database.md) — FalkorDB: why Redis-module graph over Neo4j
- [embedder.md](./embedder.md) — text → vector: Voyage default + local and no-embedder alternatives
- [llm-config.md](./llm-config.md) — extraction model (OpenAI-compatible, OpenRouter default) and chat model (Anthropic SDK)
- [consumer-integration.md](./consumer-integration.md) — how consumer apps actually talk to the brain (typed-client default + MCP discovery for LLM harnesses; what "MCP wire protocol" means in practice). Narrative + quickstart.
- [consumer-api.md](./consumer-api.md) — exhaustive per-tool reference: every method's arguments, return shapes, error cases. The doc you keep open in another tab while coding.
- [value-prop.md](./value-prop.md) — honest accounting of what's valuable in this project, what isn't yet, and what unlocks more value
- [human-edit-surface.md](./human-edit-surface.md) — the PWA graph browser/editor as a peer to chat
- [storage-policy.md](./storage-policy.md) — Graphiti is the only persistent store; everything else is deferred
- [genericity-rule.md](./genericity-rule.md) — shared brain for anyone, not built around one author's workflow
