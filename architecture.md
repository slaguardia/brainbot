# Brainbot — Architecture & Phased Build Plan

A self-hosted personal knowledge service. The brain is the only thing that holds structured truth about you; everything else — terminal harnesses, mobile apps, narrow scoring agents — is a thin consumer that calls in. One graph, N consumers.

**Dual purpose:** this is a daily-driver tool *and* a portfolio piece. Every architectural decision should be defensible to a senior-eng interviewer. The writeup is half the deliverable. Per-component working docs (current state, tradeoffs, alternatives considered) live in [`docs/`](./docs/README.md).

## Goal

One self-hosted brain (Graphiti on FalkorDB) reached over HTTP + MCP by any number of small consumer apps. Each consumer stays stateless and narrow because the cross-app knowledge lives in the brain.

The brain itself is graph-shaped end to end. There is no markdown substrate, no file watcher, no derived projection of the data — Graphiti is the source of truth. Consumers read what the brain knows; consumers don't keep their own parallel state.

### First-party consumers shipped with the project

These are example consumers built as part of the project to prove the contract. They are not the point of the project — the brain is.

- **Claude Code MCP** (Phase 1) — terminal harness in any project repo. `UserPromptSubmit` hook injects relevant brain context into every prompt; `SessionEnd` writes a session summary back as an episode.
- **PWA** (Phase 2) — a one-screen phone capture surface (type a thought → send → it lands in the brain), Google-auth'd at the edge. The original chat + browse/edit modes were dropped in the pivot; graph inspection is done via the FalkorDB Browser.

### Third-party consumers (the actual vision)

Apps you build later, each calling the brain over HTTP/MCP. Examples worth building once the substrate is solid:

- Job-fit scorer that consults work history + role preferences in the brain
- Reading-queue triage that knows what you've already absorbed
- Calendar prep that pulls everything you've ever captured about attendees
- Passive CRM that builds itself from "had coffee with X" captures

The brain doesn't care which consumer is asking. There's no schema migration, no per-app namespace, no profile config — just `capture(text)`, `recall(query)`, and `profile()` over the same `brain` group.

## Non-goals

- Multi-user / sharing / collab — single-user system
- Realtime collaboration features
- A general-purpose Notion competitor
- Feature breadth for its own sake — portfolio value comes from *daily use*, not surface area
- A markdown-canonical brain (considered, parked — see [docs/human-edit-surface.md](./docs/human-edit-surface.md))

## Why not just use Hermes (or similar)?

[Hermes Agent](https://github.com/nousresearch/hermes-agent) ships ~70% of what's planned here in an afternoon: self-hosted, multi-surface, scheduled automations. Worth naming explicitly because the question will come up in interviews.

The reason to build instead of adopt comes down to **memory shape**:

| Hermes (turn-shaped) | Brainbot (episode-shaped graph) |
|---|---|
| Memory triggered per chat turn — `prefetch` before, `sync_turn` after | Anything can be an episode — a captured thought, a journal entry, a session summary, a status change |
| Strings + embeddings, semantic recall | Typed entities + relations, structured queries |
| One canonical entity only if vector search lands; otherwise fragments silently | Explicit entity dedup; one node per thing, all relations attached |
| No bi-temporal — old facts rot in place | `valid_from` / `valid_to` on every fact; corrections invalidate cleanly |
| Degrades gracefully under bad data (fuzzy match still finds things) | Fails brittle if extraction drifts (wrong edge name = empty result) |

Bet being made: **structured queries over your own life are worth the cost of running an LLM-extraction layer on every write.** "What people have I talked to about X in the last 30 days, and what did each of them say?" should be a graph query, not a vector search across chat turns.

The risk is real and acknowledged in the [extraction-quality](#extraction-quality-the-real-risk) section below.

## Why this shape (the key decisions)

| Decision | Why |
|---|---|
| **graphiti-core (Apache 2.0) for the graph engine** | Bi-temporal property graph, schema-flexible (string-typed nodes/edges, no migrations), LLM extraction on every write. The brain service constructs graphiti-core **in-process** — the standalone Graphiti MCP server was dropped because it hid the extraction levers a personal brain needs (see `brain/README.md`). |
| **FalkorDB as the graphiti-core backend** | Redis-module, ~6× more memory-efficient than Neo4j. Fits comfortably on a small VPS. The only persistent store. |
| **A smart `brain` service, thin consumers** | The brain (FastAPI, graphiti-core in-process) owns all the smarts: the decompose→extract capture pipeline and the recall scoring. Consumers (the PWA, Claude Code, your apps) stay dumb. The PWA is just a one-screen capture client that proxies to the brain's `/capture`. |
| **Narrow contract: capture / recall / profile** | The brain exposes three operations, not the full graph-introspection toolset. Bulk graph editing/browsing isn't a consumer concern — use the FalkorDB Browser. The file-canonical alternative for human editing was considered and parked — see [docs/human-edit-surface.md](./docs/human-edit-surface.md). |
| **Two front doors** | Plain HTTP/JSON for typed consumers (the default); MCP at `/mcp` for Claude Code and other LLM-tool-discovery harnesses. Same three operations behind both. |
| **No second store** | FalkorDB (via graphiti-core) is the only persistent store in early phases. No Postgres, no SQLite. Logs go to stderr. If observability or queueing later genuinely demand a second store, it gets added then — not preemptively. |

## Surfaces

The PWA is **one screen: capture.** The original three-mode vision (chat + browse/edit + capture) was dropped in the pivot — once the brain became a service for many consumers, a privileged human UI stopped being the point. Browsing/editing the graph is done with the FalkorDB Browser; a conversational consumer, if ever worth building, is a separate app.

| Surface | What it's for | Primary use |
|---|---|---|
| **PWA capture** | Single-purpose append: textarea, send, optimistic ack in <100ms; proxies to the brain's `/capture`. Google sign-in + email whitelist at the edge. | "Save this thought before it leaves my head" — from the phone home screen |
| **Claude Code** | Ambient memory in any project repo. `UserPromptSubmit` hook `recall`s relevant context and prepends it to every prompt; `SessionEnd` writes a session summary back via `capture`. | terminal work that should remember across sessions |
| **Your consumers** | Any app calling `capture`/`recall`/`profile` over HTTP (job-fit scorer, calendar prep, …). | app-specific intelligence backed by the shared brain |

## Architecture

```mermaid
flowchart TB
  subgraph Surfaces["Surfaces / consumers"]
    PWA_UI["PWA — phone capture<br/>one screen: type → send"]
    CC["Claude Code — any project repo<br/>MCP recall + SessionEnd capture"]
    APP["Other consumers<br/>(job-fit scorer, hooks, …)"]
  end

  subgraph VPS["Single VPS (~$7/mo)"]
    CADDY["Caddy + Let's Encrypt"]
    OAUTH["oauth2-proxy<br/>Google OIDC + email whitelist"]

    subgraph DockerNet["docker compose internal network (no public ports)"]
      PWA_BE["PWA backend (Node)<br/>thin proxy → /capture"]
      BRAIN["brain service (FastAPI)<br/>graphiti-core in-process<br/>HTTP: /capture /recall /profile<br/>MCP: /mcp (capture·recall·profile)"]
      FALKOR[("FalkorDB<br/>property graph + vector<br/>SOURCE OF TRUTH")]
    end
  end

  ANTH["Anthropic API<br/>Sonnet (decompose) · Haiku (extraction)"]
  VOY["Voyage API<br/>embeddings"]

  PWA_UI -->|"HTTPS brain.{domain}"| CADDY
  CC -->|"HTTPS MCP brain.api.{domain}"| CADDY
  APP -->|"HTTPS brain.api.{domain}"| CADDY
  CADDY -->|"forward_auth (PWA host)"| OAUTH
  OAUTH -->|authenticated| PWA_BE
  CADDY -->|"bearer (API host)"| BRAIN
  PWA_BE -->|POST /capture| BRAIN
  BRAIN --> FALKOR
  BRAIN --> ANTH
  BRAIN --> VOY
```

### Data flow — capture + recall

```
1. Phone, on the train: open the PWA → type a thought → tap send.
   POST /api/capture → PWA backend proxies to the brain's POST /capture.
   The brain decomposes the text + extracts each fact (a few seconds).
   The UI shows a "captured" toast immediately (optimistic) — it does not wait.

2. Later, any consumer asks a question:
   GET /recall?q=... → the brain runs hybrid search over FalkorDB (graphiti-core),
   scores each fact against the query, returns the ranked facts.
   The consumer's own LLM filters/synthesizes from there.

3. Need the whole picture, not one answer:
   GET /profile → every currently-true fact about the user, newest first.
```

The brain's `/capture` awaits the full decompose+extract pipeline; the PWA acks optimistically so the user never waits on it. An async queue is a later option (Phase 3) if very large captures need it — not before.

### Data flow — Claude Code in a project repo

```
1. Open a session in any repo where the brain hooks are installed.
   UserPromptSubmit fires on every prompt → calls the brain's recall
   → prepends a <relevant-memory> block. The user never types "search the brain";
   it's ambient.

2. Use the session normally. SessionEnd fires when the session closes →
   summarizes the transcript with Haiku → capture's it back to the brain.

3. Tomorrow, in any repo: ask "what did I work on yesterday?" →
   the inject hook surfaces yesterday's session summary.
```

## Stack

| Component | Choice | Notes |
|---|---|---|
| **Graph engine** | graphiti-core (Apache 2.0), pinned `==0.29.1` | Constructed in-process by the brain service. https://github.com/getzep/graphiti |
| **Graph DB** | FalkorDB | Redis-module backend for graphiti-core |
| **Brain service** | Python + FastAPI (`brain/`) | Constructs graphiti-core directly; serves `capture`/`recall`/`profile` over HTTP + an MCP face at `/mcp` |
| **MCP** | The brain's own MCP face (`/mcp`) | Replaces the retired standalone Graphiti MCP server; for Claude Code |
| **PWA frontend** | Vanilla TS + Vite (`pwa/`) | One screen (capture). No meta-framework — a single page + one route doesn't justify one |
| **PWA backend** | TypeScript, raw `node:http` | Thin proxy: `POST /api/capture` → brain `/capture`. No brain logic |
| **Auth** | Bearer token at Caddy for the brain API; Google sign-in + email whitelist (oauth2-proxy at the edge) for the PWA | Per-identity access + easy revocation on phones; internal services (brain, FalkorDB) never publish ports. |
| **Deployment** | Single docker-compose on a small VPS | All services on one box. Iteration: `git pull && docker compose up -d --build`. |
| **Extraction model** | Claude Haiku (`BRAIN_LLM_MODEL`, native Anthropic SDK) | Cheap; runs on every episode write during extraction. Swap via env. |
| **Decomposition model** | Claude Sonnet (`BRAIN_DECOMPOSE_MODEL`) | Rewrites raw capture into named-subject atomic facts; quality matters more here. |
| **Embedder** | Voyage (`voyage-3-lite`, `BRAIN_EMBED_MODEL`) | Vector embeddings for hybrid recall. |
| **TLS / domain** | Caddy + Let's Encrypt | UFW restricts to 80/443; fail2ban handles abuse |

## Phased plan

Each phase is broken into bite-size tasks in [`plans/`](./plans/). The list here is the executive summary.

### Phase 0 — VPS substrate
- Small VPS (~8GB RAM is comfortable), Ubuntu LTS
- Tailscale for ops access, UFW + fail2ban
- Docker + docker-compose pattern, non-root user

### Phase 1 — Brain online, agent reads it
**Outcome:** Claude Code in any configured project repo can query the graph and gets relevant memories injected automatically. Initial seed content migrated in.

**On migrators:** the brain is meant to swallow messy personal data from wherever you've been hoarding it. Notion is the first source we ship a migrator for, but it's one of many — Obsidian/markdown vaults, Roam/Logseq, Apple Notes, plain-text journals, and anything else with an export are all plausible siblings. The migrator's contract is generic (produce `{ name, body, reference_time }` payloads; hand to a shared dispatcher; Graphiti's per-write extraction handles routing and dedup), so adding a new source is sibling-file work, not a refactor. Pluggability stays implicit until a second migrator forces a shared layer — premature `migrate/lib/` extraction is exactly the kind of overdesign this project avoids.

Detail: [`plans/phase-1-graph-online.md`](./plans/phase-1-graph-online.md)

**Definition of done:** the agent surfaces relevant context from the graph without being told where to look.

### Phase 2 — brain service + one-screen capture PWA
**Outcome:** Re-scoped from the original three-mode (chat + browse/edit + capture) vision. The pivot made the brain the product, so Phase 2 shipped the standalone `brain` service (FastAPI, graphiti-core in-process) and a single-screen capture PWA that proxies to it, Google-auth'd at the edge. Chat and browse/edit were dropped (FalkorDB Browser covers inspection).

**Definition of done — the smoke test:** capture a thought on the phone → tap send → "captured" toast in <100ms → the episode lands in the brain (visible in the FalkorDB Browser within seconds).

### Next — document-substrate refactor (supersedes the old Phase 3–4)
**Reconsidered:** the graph isn't earning its keep — `recall()` never traverses, so its only real value was dedup + bi-temporal, not relationships. The go-forward is a document substrate: source-of-truth docs + derived section-chunks on pgvector, with the brain as a reusable intelligence library (`recall` / `profile` / `map`). The old write-back and hardening work folds into that.

Detail: [`plans/document-substrate-exploration.md`](./plans/document-substrate-exploration.md); rationale in [`LEARNINGS.md`](./LEARNINGS.md) Chapter 6.

## Extraction quality (the real risk)

Cost isn't the constraint — extraction quality is. Every episode write asks the extraction model "what entities are in this text?" When it's wrong, the graph silently fragments:

- "Coffee with Sarah from Acme" creates a *new* `Acme` node instead of linking to the existing one because context was thin
- "Outreach to a founder" one week, "DM'd a CEO" the next — does the extractor link them as the same edge type?
- Over-specifying edge types up front (`outreach_to` vs `messaged` vs `dm_sent`) means surgical queries miss 2/3 of the data

Three hedges, all lightweight:

1. **Hybrid retrieval from day one.** Every query does vector search *and* graph lookup, returns the union. Graceful degradation when the graph is fragmented.
2. **Correction path.** When extraction gets something wrong, today you re-capture a corrective fact (the bi-temporal model supersedes the old one) or fix it directly in the FalkorDB Browser. A first-class human-edit surface is a parked requirement — see [docs/human-edit-surface.md](./docs/human-edit-surface.md).
3. **Weekly dedup audit** (Phase 4). Script surfaces near-duplicate entities for merge. Catches drift before it compounds.

If these hedges fail and the graph noticeably degrades, the fallback is honest: pull a Hermes-style turn-shaped provider in as a second memory layer alongside the graph. Not a defeat — just an admission that some recall is better as semantic search.

## Open questions

1. **Ingestion model cost ceiling.** The brain calls an LLM at every episode write to extract entities (plus one decomposition call per capture). At expected volume with Haiku, probably <$5/mo. Confirm by counting expected captures per week × tokens-per-episode.
2. **~~PWA framework: Svelte vs Next.~~** Resolved: vanilla TS + Vite. A one-screen capture app + one backend route doesn't justify a meta-framework.
3. **~~Mutation API granularity.~~** Moot for now — the browse/edit UI was dropped in the pivot; the brain's contract is capture/recall/profile, and a human-edit surface is parked (see [docs/human-edit-surface.md](./docs/human-edit-surface.md)).
4. **~~Cookie-based auth on the PWA.~~** Resolved: Google sign-in + email whitelist enforced at the edge by oauth2-proxy (session cookie, no bearer on the phone).

## Honest tradeoffs (signed off)

- **You own the brain service.** No "Claude Code update will fix that" — when extraction or recall misbehaves, you debug the brain (`brain/`). That's also what makes the extraction tuning yours.
- **The capture PWA is yours forever.** Polish, mobile UX, install flow — all your problem. Counterpoint: it's also what makes the experience yours.
- **No human-edit UI yet.** Graph-canonical means there's no Obsidian to fall back on, and the browse/edit surface was dropped in the pivot — corrections go through re-capture or the FalkorDB Browser until a real edit surface is built. A real gap (parked, not solved).
- **Schema flex is real but not free.** graphiti-core's edge/node typing is string-based; nothing stops you from creating `outreach_to` and `outreached_to` as different edge types and getting confused. Discipline matters; convention beats configuration.
- **Episode writes can't block the UI.** 1–3s LLM extraction means every write surface needs optimistic UX with background error toasts. Designed for, not papered over.

## Portfolio artifacts (build in public)

The project is a daily-driver tool *and* an interview asset. Each phase produces something a hiring manager can see in 90 seconds without running code.

| Phase | Public artifact |
|---|---|
| 1 | Twitter thread + blog post: "Why I built my second brain on a property graph instead of a vector store." Hermes-vs-graph table + the Graphiti/FalkorDB rationale. |
| 2 | 10-second screen recording: phone home screen → tap icon → type a thought → send → "captured" toast. Caption: "Two seconds from thought to brain." Plus a screenshot of the extracted entities in the FalkorDB Browser. |
| 3 | Twitter thread: "Three capture surfaces, one brain — a postmortem on quick-capture UX." Honest writeup of what worked, what didn't, what's still rough. |
| 4 | Long-form writeup at a public route: the full decision history (sourced from the per-component docs in [`docs/`](./docs/README.md)), what surprised, what to do differently. Becomes the link in every job application. |

**Discipline:** ship the artifact for each phase *before* starting the next phase. The writeup is half the deliverable.

## References
- [Graphiti repo](https://github.com/getzep/graphiti)
- [Graphiti MCP server](https://github.com/getzep/graphiti/tree/main/mcp_server)
- [FalkorDB integration writeup](https://docs.falkordb.com/agentic-memory/graphiti-mcp-server.html)
- [Anthropic SDK (TS)](https://github.com/anthropics/anthropic-sdk-typescript)
- [Hermes Agent (the alternative)](https://github.com/nousresearch/hermes-agent)
