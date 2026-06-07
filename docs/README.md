# Brainbot docs

All project documentation lives in this folder and describes the system **as it
is now**: a four-layer **control plane for personal apps** — a Postgres +
pgvector brain (**sources** split into embedded **chunks**, read via `recall` /
`doc` / `map`) at the bottom, a shared Caddy/SSO edge, a shared web-toolkit, and
the apps built on top. Design history, including the graph era and why it was
dropped, lives in [`learnings.md`](./learnings.md) (append-only); everything else
here discards reversed decisions instead of accumulating them.

## Start here

- [architecture.md](./architecture.md) — the brain + edge: goal, consumers, key decisions, stack, security model, and how it got here.
- [app-platform.md](./app-platform.md) — the four-layer platform: how to build and ship app N+1 — the app contract, the two-kinds-of-data rule, the edge, the launcher. Read with `architecture.md`.
- [positioning.md](./positioning.md) — where brainbot sits in the memory landscape: vs NotebookLM, Supermemory and the Mem0-class agent-memory APIs, the Obsidian-as-AI-brain movement, and assistants' built-in memory — and what makes this cell unique.
- [rag-primer.md](./rag-primer.md) — plain-English primer with analogies: what RAG is, how brainbot's hybrid retrieval works, what the tool names (LangChain / Pinecone / pgvector) mean, and how brainbot compares to Obsidian/Notion. Start here instead if the field is new to you.

## The brain

- [brain-architecture.md](./brain-architecture.md) — the living design doc: the librarian model, the interfaces, currency by construction, settled principles, the RAG experiment backlog, open questions. Point at this during design discussions.
- [brain.md](./brain.md) — the service itself: ingest pipeline, the reads, modules, config, how to run it.
- [embedder.md](./embedder.md) — text → vector: Voyage default, local and no-embedder alternatives, the tradeoff table.

## The platform (building apps on the brain)

- [app-platform.md](./app-platform.md) — the governing platform doc: the four layers, the app contract, polyglot backends, the two-kinds-of-data rule, the edge, the launcher, the repo layout.
- [web-toolkit.md](./web-toolkit.md) — L3: the shared frontend package (design tokens, app shell, components, service-worker + manifest, brain client, session) every app's PWA is built from.

## Consumers

- [consumer-api.md](./consumer-api.md) — the consumer contract, per operation: shapes, cache rules, 404 semantics. The doc you keep open while coding.
- [consumer-integration.md](./consumer-integration.md) — how an app talks to the brain, in brief. Narrative companion to the reference.
- [pwa.md](./pwa.md) — the first-party PWA: layout, dev workflow, deploy, the #apps launcher.

## Principles & history

- [genericity-rule.md](./genericity-rule.md) — shared brain for anyone, not built around one author's workflow.
- [learnings.md](./learnings.md) — append-only evolution history: what was believed, what broke, what changed, chapter by chapter.
