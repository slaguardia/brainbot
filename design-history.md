# Brainbot — Design History

This is the iteration story for brainbot: what was considered, what was picked, and *why* the design landed where it did. [`architecture.md`](./architecture.md) describes the current shape; this doc describes the path to it.

The portfolio half of the project lives here. Most personal AI projects skip the "why" — they just present the final stack as if it dropped from the sky. The honest version names alternatives, tradeoffs, things that were almost picked, and things that were tried and parked.

Decisions are listed in roughly the order they were settled.

---

## 1. Memory shape — graph, not turn-shaped

**Decision:** episode-shaped graph (entities + edges + bi-temporal facts), not a turn-shaped vector store of chat history.

**Alternative considered:** [Hermes Agent](https://github.com/nousresearch/hermes-agent) and similar turn-shaped systems — strings + embeddings, semantic recall per chat turn. Ships ~70% of brainbot's surface area in an afternoon.

**Why graph won:** structured queries over your own life are worth the LLM-extraction cost on every write. "What people have I talked to about X in the last 30 days, and what did each of them say?" should be a graph traversal, not a vector search across chat turns. Bi-temporal handling means corrections invalidate cleanly instead of fact-rot-in-place.

**The honest cost:** extraction is ~$0.0016 per write at Haiku rates and 1–3s of latency per episode. The graph fragments brittlely if extraction drifts. Three hedges (called out in [architecture.md](./architecture.md#extraction-quality-the-real-risk)) keep it viable: hybrid retrieval, the human-edit surface in the PWA, and a weekly dedup audit.

**The honest fallback:** if extraction quality fails despite the hedges, add a vector layer alongside the graph (Phase 4, Task 4.9). Not a defeat — an admission that some recall is better as semantic search.

The Hermes-vs-graph comparison table lives in [architecture.md](./architecture.md#why-not-just-use-hermes-or-similar).

---

## 2. Graph engine — Graphiti

**Decision:** [Graphiti](https://github.com/getzep/graphiti) (Apache 2.0).

**Alternatives considered:**
- Roll-our-own entity extraction + storage — full control, but 6+ months of work to reach what Graphiti does out of the box.
- LangGraph / LlamaIndex memory abstractions — heavier, more opinionated, less aligned with the bi-temporal-facts model.
- Just a vector store — already ruled out by Decision 1.

**Why Graphiti:** bi-temporal property graph is exactly the right primitive. Schema-flexible (string-typed nodes/edges, no migrations to manage). Official MCP server already shipped. Apache 2.0 license. The whole "LLM extracts entities + edges on every write" is the part you don't want to build yourself.

---

## 3. Graph DB — FalkorDB

**Decision:** [FalkorDB](https://www.falkordb.com) (Redis module).

**Alternative considered:** Neo4j. Industry-standard property graph; mature; enormous ecosystem.

**Why FalkorDB:** ~6× more memory-efficient than Neo4j. Fits comfortably on a small VPS. It's also Graphiti's default backend for the MCP server, so the integration story is "just work" instead of "wire it up."

**The honest tradeoff:** Neo4j has more tooling around it (Bloom, Cypher Shell, Aura). FalkorDB is younger and the ecosystem is thinner. For a single-user system, the memory win matters more than the tooling depth.

---

## 4. MCP scope — Claude Code only, not the PWA

**Decision:** the Graphiti MCP server is wired into Claude Code (terminal harness). The PWA bypasses MCP and talks directly to Graphiti's REST endpoint over the docker network.

**Alternative considered:** route everything through MCP for consistency.

**Why split:** MCP is the right protocol for *terminal-tool integration* — Claude Code's tool list is dynamic, model-aware, JSON-shaped, and benefits from a standard transport. The PWA is a single Node process running on the same host as Graphiti; routing its calls through MCP would mean serializing/deserializing JSON over an extra hop for no gain.

**The principle:** use MCP where you're getting the protocol's actual benefits. Don't use it as a default just because it's available.

---

## 5. The file-canonical detour (parked)

**Decision:** graph-canonical (FalkorDB is the source of truth). The "markdown + frontmatter as canonical, graph as derived lens" approach is **parked**, not killed.

**The detour:** mid-design, I drew up a [shared-brain mermaid](./shared-brain-architecture.mermaid) that put markdown files in a git-versioned directory at the center, with a file watcher feeding episodes into Graphiti. Human and agent would both read/write files symmetrically (Obsidian-style). The graph would be a read-time projection.

**Why it was tempting:**
- Symmetric I/O for human + agent — same store, same operations.
- Editing brain data is "just open the file in Obsidian" — solves the human-edit problem for free.
- Git is your version history.
- No bespoke graph editor UI to build.

**Why it was parked:**
- Two stores to keep in sync (files ↔ graph) — the watcher's diff/conflict handling is a real engineering problem.
- The graph is then never *quite* the source of truth for queries (you have to handle "the file was edited but the watcher hasn't re-extracted yet").
- Bi-temporal correctness is harder when the file system is the write path — there's no "old fact invalidated at time T" semantics in plain files.

**Why it isn't dead:** the file-canonical model is the most natural answer to the human-edit-the-brain requirement. If the graph editor surface in Phase 2 turns out to be too heavy or the bad-extraction problem becomes the dominant pain, the fallback is "let the human edit a markdown view of an episode, parse changes back into mutations." That's a partial revival of the file-canonical idea without committing to it as the substrate.

---

## 6. Human-edit-the-brain surface — committed to graph-canonical

**Decision:** the PWA exposes a real graph browser/editor as a peer to chat and capture. Episodes, entities, and edges are all directly viewable and editable. Edits hit Graphiti as mutations.

**Alternatives considered:**
- **Markdown-as-edit-format:** render a node/episode as markdown, edit in a markdown editor pane, parse the markdown back into graph mutations on save. Discussed and rejected — the parser layer is a real cost and the user wanted the simpler shape.
- **Read replica for speed:** project the graph into a denormalized read store (SQLite or similar) so list views are fast. Rejected as premature — there's no measured perf problem yet.
- **No editor, only bi-temporal correction:** humans correct bad extractions by writing new contradictory episodes and trusting the bi-temporal store to invalidate the old fact. Rejected — relies entirely on the extractor doing the right thing, gives the human no direct lever.

**Why a real graph browser:** without it, "the graph is the source of truth" means "the human has no direct lever." With it, the human can fix bad extractions, rename entities, prune wrong edges. This is the strongest hedge against the bi-temporal-correction-only failure mode of graph-canonical systems — and the reason graph-canonical is viable at all.

**The honest cost:** this is real product surface area. Entity card, episode editor, merge modal, search, infinite-scroll feed — all need actual phone testing. It's a Phase 2 workstream of its own.

---

## 7. Strip the personal context (the genericity rule)

**Decision:** brainbot is designed as a generic "shared brain anyone could deploy and use," not built around the original author's specific situation.

**What got stripped:**
- **Postgres / `personal` DB / `brain` schema.** The original design assumed an existing Postgres instance running OpenClaw on the VPS. Once OpenClaw was out of scope, the only argument for Postgres ("we already have it") evaporated.
- **OpenClaw decommission as a phase.** Replaced with nothing — the project no longer assumes any prior agent-hosting stack.
- **`draft_outreach` / `brain.drafts` / `Outreach` entity / job-hunt context.** A specific workflow built around the original author's job-hunt use case. Replaced with generic tools (`search_brain`, `get_entity`, `add_episode`) the agent composes — workflows are things the user discovers, not things the architecture bakes in.
- **iOS Shortcut as the primary capture path.** Demoted to one option among several (PWA capture screen is the primary; the iOS Shortcut is convenience).
- **Notion as *the* source of seed data.** Reframed as *a* source — the first migrator we ship, not the only one. The migrator's contract is generic, and other sources (Obsidian, Roam/Logseq, Apple Notes, plain-text journals) are demand-driven siblings. We did *not* pre-create a `migrate/sources/` or `migrate/lib/` structure; that's a refactor the second migrator earns, not preemptive overdesign.
- **VPS-vendor-specific assumptions.** Replaced with "small VPS" wherever specifics weren't load-bearing.

**Why:** the project is dual-purpose — daily driver *and* portfolio piece. The portfolio half only works if the architecture defends as a generic system. Burying the author's specific situation in the core makes it look like a personal hack rather than a product.

---

## 8. No second store in early phases

**Decision:** Graphiti (FalkorDB) is the *only* persistent store in Phases 1–3. No Postgres, no SQLite, no relational anything.

**What this means concretely:**
- **Migration log:** none. The Notion → Graphiti migrator is a one-shot seed. Re-runs re-post everything (Graphiti's bi-temporal handling means re-runs link to existing entities rather than silently fragmenting, but each re-run pays the extraction cost).
- **Capture queue:** none in Phase 2 — captures are synchronous (1–3s wait for extraction). Phase 3 introduces an in-memory queue when the iOS Shortcut surface forces sub-100ms response. Even then: in-memory only, no persistent spool. Crash means losing in-flight captures, accepted as a personal-use tradeoff.
- **Tool-call observability:** stderr logs in Phase 2. `docker logs pwa` is the dashboard. `/admin` UI moves to Phase 4 where it belongs.

**Iterations to get here:**
- **First pass (cut):** Postgres for everything (drafts, tool_calls, migration_log, pending_episodes, dedup_candidates). Justified by "we already have it." Cut when OpenClaw decommissioned.
- **Second pass (cut):** SQLite as a single-file replacement for Postgres. Embedded in the PWA process, no extra container. Same five tables, just in SQLite. Cut after explicit pushback that this was still overkill.
- **Third pass (current):** no operational store at all in early phases. The five "needs" the previous passes were trying to solve are either deferred until they're real (`/admin`, persistent queue) or simply not needed (migration log for a one-shot import).

**Why this is the right answer:** every persistent store is a decision a downstream user has to inherit. Deferring the decision until the data shape is obvious means picking the right store later, not the most-capable store now. The `/admin` Phase 4 task explicitly punts the choice ("default to rotated ndjson; reach for SQLite only if structured queries become necessary").

---

## 9. Provider-neutral LLM config

**Decision:** Graphiti's extraction model is configured via the OpenAI-compatible API (`OPENAI_API_KEY` + `OPENAI_BASE_URL` + `MODEL_NAME`), defaulting to OpenRouter.

**Alternative considered:** hard-code Anthropic SDK calls.

**Why provider-neutral:** the OpenAI-compatible API is the lingua franca. It lets a downstream user swap to OpenAI direct, Together, Groq, local Ollama, vLLM, or anything else with a config change. OpenRouter as the default gives access to every major model (and many local/OSS ones) from one signup, including Anthropic models when that's what you want.

The chat model in the PWA still uses the Anthropic SDK directly (because tool-use streaming is the killer feature and the SDK's `stream` helper is the right abstraction for it).

---

## 10. Co-hosted Ollama — parked

**Decision:** running an extraction model locally on the VPS via Ollama is a Phase 4 backlog item, not a default.

**Alternative considered:** ship Ollama in the docker-compose stack from Phase 1 to eliminate per-extraction API spend.

**Why parked:** Ollama-on-CPU at the VPS sizes considered would be slow enough to bottleneck the whole capture pipeline. CPU-only extraction in a single-tenant deployment also doesn't justify the extra moving part. Revisit when:
- VPS gets a GPU (or migration to a GPU-enabled host happens for other reasons), or
- Per-extraction API spend becomes the dominant cost line, or
- Privacy requirements force local inference.

The `OPENAI_BASE_URL` plumbing already accepts `http://host.docker.internal:11434/v1` — the door is open, the path is just deferred.

---

## What the next round of decisions will look like

When Phase 2 ships, a few things become real for the first time:

- **Graph editor mutation API granularity** — the Task 2.10 list is six mutations. Real usage will reveal the seventh and eighth. Add them as needed.
- **Sync vs async capture latency** — synchronous captures will either feel fine or feel terrible. Phase 3 has the queue work ready to go either way.
- **Persistent observability** — the Phase 4 `/admin` task is currently "pick the simplest store that fits the data." That decision lives there and gets made when it's actually due.

The pattern: pick the simplest thing that works *for the next phase only*. Defer every decision you don't have to make. Document the iteration so the deferral is intentional, not lazy.
