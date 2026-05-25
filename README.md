# brainbot

A self-hosted shared brain. One source of truth, two surfaces:

- **PWA** — phone + desktop daily driver. Three modes against one graph: chat with an agent, browse and edit graph data directly, capture thoughts in two seconds.
- **Claude Code MCP** — terminal harness in any project repo. Reads from the same brain ambiently via a `UserPromptSubmit` hook; writes session summaries back via `SessionEnd`.

Built on [Graphiti](https://github.com/getzep/graphiti) (bi-temporal property graph) backed by [FalkorDB](https://www.falkordb.com), with a custom TypeScript agent on `@anthropic-ai/sdk`. Single small VPS.

## Why this exists

Two reasons:

1. **Daily-driver tool.** Notion is a great editor and a poor substrate for "answer questions about my life over time." A property graph with bi-temporal facts and entity dedup gives structured queries Notion can't.
2. **Portfolio piece.** Most "I built an AI agent" projects look the same: LangChain, Pinecone, Vercel. This one defends real architectural decisions — graph-shaped vs turn-shaped memory, custom harness vs adopting [Hermes](https://github.com/nousresearch/hermes-agent), MCP for terminals only vs everywhere, graph-canonical vs file-canonical (the most interesting fork — see [`docs/human-edit-surface.md`](./docs/human-edit-surface.md)).

The full reasoning lives in [`architecture.md`](./architecture.md). Per-component working docs (current state + tradeoffs + alternatives considered) live in [`docs/`](./docs/README.md).

## Status

| Phase | Status | Detail |
|---|---|---|
| 0 — VPS + Docker substrate | ✅ done | Small VPS, Ubuntu LTS, UFW, Caddy, Tailscale |
| 1 — Brain online, Claude Code reads it | 🟡 in plan | [`plans/phase-1-graph-online.md`](./plans/phase-1-graph-online.md) |
| 2 — PWA: chat + browse/edit + capture | 🟡 in plan | [`plans/phase-2-pwa-harness.md`](./plans/phase-2-pwa-harness.md) |
| 3 — Write-back loop + capture polish | 🟡 in plan | [`plans/phase-3-writeback.md`](./plans/phase-3-writeback.md) |
| 4 — Hardening + life expansion | 🟡 in plan | [`plans/phase-4-hardening.md`](./plans/phase-4-hardening.md) |

## The bet, in one paragraph

Most personal-AI memory systems are turn-shaped: they remember chat turns and retrieve them by vector similarity. That's fine for "what did we talk about" but degrades for "what people have I talked to about X in the last 30 days, and what did each of them say." Brainbot is episode-shaped: anything can be an episode (a captured thought, a journal entry, a session summary, a status change), entities get extracted and deduped on write, queries can traverse relations. The cost is an LLM extraction call per write (~$0.0016) and brittleness if extraction drifts. Three hedges: hybrid retrieval (vector + graph union) from day one, a direct graph editor surface in the PWA so humans can fix bad extractions, and a weekly dedup audit.

The honest comparison table with Hermes lives in [`architecture.md`](./architecture.md#why-not-just-use-hermes-or-similar).

## Repo layout

```
brainbot/
├── architecture.md              — current architecture + decision rationale
├── docs/                        — per-component working docs (memory model, embedder, MCP, etc.)
├── plans/
│   ├── phase-1-graph-online.md
│   ├── phase-2-pwa-harness.md
│   ├── phase-3-writeback.md
│   └── phase-4-hardening.md
├── compose/                     — docker-compose, Caddyfile (FalkorDB + Graphiti + PWA)
├── migrate/                     — one-shot migrators (Notion first; pluggable for other messy-data sources)
├── scripts/                     — smoke tests + ops helpers
└── templates/
    └── claude-code-client/      — drop-in MCP config + UserPromptSubmit hook for any project repo
```

Code lands incrementally — `pwa/` will be added in Phase 2.

## Running it (fresh install)

The Phase 1 stack is two compose services: `falkordb` (graph store) and `graphiti` (the MCP + REST server that does entity extraction on every write). Caddy is VPS-only and sits in front of `graphiti` with TLS + bearer auth. No second store — Graphiti is the only persistent service in early phases.

### 1. Configure env

```sh
cd compose
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (LLM extraction) and VOYAGE_API_KEY (embeddings) —
# these are the defaults baked into graphiti-config.yaml. Also set BRAIN_DOMAIN +
# BRAIN_BEARER_TOKEN, and NOTION_TOKEN if you'll run the migrator.
#
# To swap providers: see comments in graphiti-config.yaml. OpenAI / OpenRouter /
# local Ollama are all supported but require editing the yaml, not just .env.
```

### 2. Bring the stack up

**Local laptop (no Caddy, no TLS, port exposed on 127.0.0.1):**
```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
docker compose ps                       # both healthy?
```

`graphiti` is at `http://127.0.0.1:8000`. `.env`'s `BRAIN_URL` should be `http://127.0.0.1:8000` for local runs.

**VPS (with the Caddy vhost from `compose/Caddyfile` already serving `brain.{your-domain}`):**
```sh
docker compose up -d
docker compose ps
```

`.env`'s `BRAIN_URL` should be `https://brain.your-domain.com`.

### 3. Smoke test

```sh
python scripts/smoke_brain.py            # post first episode + verify node
python scripts/smoke_brain.py --second   # post follow-up + assert no dup nodes
```

If the first run round-trips, Graphiti is wired correctly and the extraction model is reachable.

### 4. Migrate seed content (optional)

The migrator is the surface that turns messy personal data into a seeded brain. Notion is the first source we ship one for — others (Obsidian/markdown vaults, Roam/Logseq, Apple Notes, plain-text journals) are demand-driven and would live as sibling files in `migrate/`. The Notion migrator itself is domain-agnostic — point it at any Notion database or page id:

```sh
python migrate/notion_to_graphiti.py --target <notion-id> --kind auto --dry-run
python migrate/notion_to_graphiti.py --target <notion-id> --kind auto
```

`--dry-run` prints the planned episodes without writing. The migrator is meant to be a one-shot seed — re-running it currently re-posts everything (Graphiti's bi-temporal handling means corrections are linkable, not silently duplicated, but the cost-per-extraction adds up). If incremental re-runs become important, that's when to add a tracking layer.

### 5. Wire Claude Code (optional)

See [`templates/claude-code-client/INSTALL.md`](templates/claude-code-client/INSTALL.md) for how to drop the MCP server entry and the `UserPromptSubmit` memory injection hook into any of your project repos.
