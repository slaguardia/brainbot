# Brainbot docs

All project documentation lives in this folder and describes the system **as it
is now**: a Postgres + pgvector document store — **sources** (canonical,
human-edited docs) split into embedded **chunks**, read via `recall` / `doc` /
`map`. Design history, including the graph era and why it was dropped, lives in
[`learnings.md`](./learnings.md) (append-only); everything else here discards
reversed decisions instead of accumulating them.

## Start here

- [architecture.md](./architecture.md) — the system: goal, consumers, key decisions, stack, security model, and how it got here.
- [rag-primer.md](./rag-primer.md) — plain-English primer with analogies: what RAG is, how brainbot's hybrid retrieval works, what the tool names (LangChain / Pinecone / pgvector) mean, and how brainbot compares to Obsidian/Notion. Start here instead if the field is new to you.

## The brain

- [brain-architecture.md](./brain-architecture.md) — the living design doc: the librarian model, the interfaces, currency by construction, settled principles, the RAG experiment backlog, open questions. Point at this during design discussions.
- [brain.md](./brain.md) — the service itself: ingest pipeline, the reads, modules, config, how to run it.
- [embedder.md](./embedder.md) — text → vector: Voyage default, local and no-embedder alternatives, the tradeoff table.

## Consumers

- [consumer-api.md](./consumer-api.md) — the consumer contract, per operation: shapes, cache rules, 404 semantics. The doc you keep open while coding.
- [consumer-integration.md](./consumer-integration.md) — how an app talks to the brain, in brief. Narrative companion to the reference.
- [pwa.md](./pwa.md) — the first-party phone surface: layout, dev workflow, deploy.

## Principles & history

- [genericity-rule.md](./genericity-rule.md) — shared brain for anyone, not built around one author's workflow.
- [learnings.md](./learnings.md) — append-only evolution history: what was believed, what broke, what changed, chapter by chapter.
