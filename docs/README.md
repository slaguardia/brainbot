# brainbot docs

The [README](../README.md) is the short version — what brainbot is and why. This folder is the full manual. Everything here describes the system as it works today; the design history (including the knowledge-graph era and why it was dropped) is the append-only [`learnings.md`](./learnings.md).

New to the ideas behind it? Start with [`rag-primer.md`](./rag-primer.md) — plain English, no background assumed.

## Understand it

- [architecture.md](./architecture.md) — how the brain and the edge work: the design decisions, the stack, and the security model.
- [positioning.md](./positioning.md) — how brainbot compares to NotebookLM, the Mem0-class memory APIs, and the "use your notes folder as a brain" approach — and what makes it different.
- [rag-primer.md](./rag-primer.md) — what "retrieval" actually means, in plain English with analogies. Read this first if the field is new to you.
- [learnings.md](./learnings.md) — how the design got here, chapter by chapter: what was believed, what broke, what changed.

## The brain

- [brain-architecture.md](./brain-architecture.md) — the design rationale: the librarian model, why the index can't drift from your notes, the settled principles, the open questions.
- [brain.md](./brain.md) — the service itself: the ingest pipeline, the reads, the modules, the config, how to run it.
- [embedder.md](./embedder.md) — turning text into search vectors: the Voyage default, local and no-embedder alternatives, the trade-offs.

## Building apps on the brain

- [app-platform.md](./app-platform.md) — the full picture for adding another app: the shared layers, the app contract, the two-kinds-of-data rule, the edge, the launcher.
- [web-toolkit.md](./web-toolkit.md) — the shared frontend package every app's interface is built from: design, app shell, offline support, the brain client.
- [consumer-api.md](./consumer-api.md) — the read contract, operation by operation: shapes, cache rules, error semantics. The reference you keep open while coding.
- [consumer-integration.md](./consumer-integration.md) — a short narrative walkthrough of how an app talks to the brain.
- [dashboard.md](./dashboard.md) — the first-party dashboard: layout, dev workflow, deploy.

## Running it

- [quickstart.md](./quickstart.md) — run the brain locally: two containers, ingest a page, search it.
- [deployment.md](./deployment.md) — the full server runbook: provision the box, bring up the stack, add apps, and day-2 ops.
