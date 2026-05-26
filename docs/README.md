# Brainbot docs

Working docs for the current implementation. Each file explains how one piece works today and why it's shaped that way.

These are not historical — they describe the system as it is, and get updated when the system changes. If a decision gets reversed, the old version goes away with it. Each doc ends with a brief "alternatives considered" section so the tradeoff is legible without needing a separate history file.

## Start here

- [how-it-works.md](./how-it-works.md) — end-to-end walkthrough with a worked example: episode in, extraction, storage, retrieval, correction. Read this first if you're new to the project or fuzzy on what Graphiti actually does.

## Per-component

- [memory-model.md](./memory-model.md) — episode-shaped graph, bi-temporal facts, why not turn-shaped
- [graph-engine.md](./graph-engine.md) — Graphiti: extraction, dedup, storage layer
- [graph-database.md](./graph-database.md) — FalkorDB: why Redis-module graph over Neo4j
- [embedder.md](./embedder.md) — text → vector: Voyage default + local and no-embedder alternatives
- [llm-config.md](./llm-config.md) — extraction model (OpenAI-compatible, OpenRouter default) and chat model (Anthropic SDK)
- [mcp-integration.md](./mcp-integration.md) — MCP for Claude Code, REST for the PWA, and why split
- [human-edit-surface.md](./human-edit-surface.md) — the PWA graph browser/editor as a peer to chat
- [storage-policy.md](./storage-policy.md) — Graphiti is the only persistent store; everything else is deferred
- [genericity-rule.md](./genericity-rule.md) — shared brain for anyone, not built around one author's workflow
