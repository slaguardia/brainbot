# brainbot

A self-hosted personal knowledge graph + custom agent harness. One source of truth, two surfaces:

- **PWA** — phone + desktop daily driver, drafts in your voice, writes back to the graph
- **Claude Code MCP** — terminal harness in any project repo reads from the same brain

Built on [Graphiti](https://github.com/getzep/graphiti) (bi-temporal property graph) backed by [FalkorDB](https://www.falkordb.com), with a custom TypeScript agent on `@anthropic-ai/sdk`. Runs on a single $7/mo VPS.

## Why this exists

Two reasons:

1. **Daily-driver tool.** Notion is a great editor and a terrible substrate for "answer questions about my life over time." A property graph with bi-temporal facts and entity dedup gives structured queries Notion can't.
2. **Portfolio piece.** Most "I built an AI agent" projects look the same: LangChain, Pinecone, Vercel. This one defends real architectural decisions — graph-shaped vs turn-shaped memory, custom harness vs adopting [Hermes](https://github.com/nousresearch/hermes-agent), MCP for terminals only vs everywhere.

The full reasoning lives in [`architecture.md`](./architecture.md).

## Status

| Phase | Status | Detail |
|---|---|---|
| 0 — VPS + Docker substrate | ✅ done | Hostinger KVM, Ubuntu 24.04, Postgres 18, UFW, Caddy |
| 1 — Brain online, Claude Code reads it | 🟡 in plan | [`plans/phase-1-graph-online.md`](./plans/phase-1-graph-online.md) |
| 2 — PWA + custom harness | 🟡 in plan | [`plans/phase-2-pwa-harness.md`](./plans/phase-2-pwa-harness.md) |
| 3 — Write-back loop + capture polish | 🟡 in plan | [`plans/phase-3-writeback.md`](./plans/phase-3-writeback.md) |
| 4 — Hardening + life expansion | 🟡 in plan | [`plans/phase-4-hardening.md`](./plans/phase-4-hardening.md) |

## The bet, in one paragraph

Most personal-AI memory systems are turn-shaped: they remember chat turns and retrieve them by vector similarity. That's fine for "what did we talk about" but degrades for "give me the latest status of every application I've sent to AI startups in the last 30 days." brainbot is episode-shaped: anything can be an episode (a tweet, a tracker row, a journal entry, a captured thought), entities get extracted and deduped on write, queries can traverse relations. The cost is an LLM extraction call per write (~$0.0016) and brittleness if extraction drifts. The hedge is hybrid retrieval (vector + graph union) from day one and a weekly dedup audit.

The honest comparison table with Hermes lives in [`architecture.md`](./architecture.md#why-not-just-use-hermes-or-similar).

## Repo layout

```
brainbot/
├── architecture.md           — full architecture + decision history
├── plans/
│   ├── phase-1-graph-online.md
│   ├── phase-2-pwa-harness.md
│   ├── phase-3-writeback.md
│   └── phase-4-hardening.md
└── README.md
```

Code lands in subsequent phases — `compose/`, `migrate/`, `pwa/`, `harness/` directories will be added as Phases 1–2 ship.

## Running it (fresh install)

The Phase 1 stack is three compose services: `falkordb` (graph store),
`postgres` (idempotency log), and `graphiti` (the MCP+REST server that
does entity extraction on every write). Caddy is VPS-only and sits in
front of `graphiti` with TLS + bearer auth.

### 1. Configure env

```sh
cd compose
cp .env.example .env
# edit .env: pick an OPENAI_API_KEY (OpenRouter is the default provider),
# pick a Postgres password, set NOTION_TOKEN if you'll run the migrator
```

### 2. Bring the stack up

**Local laptop (no Caddy, no TLS, ports exposed on 127.0.0.1):**
```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
docker compose ps                       # all three healthy?
```

`graphiti` is at `http://127.0.0.1:8000`, `postgres` at `127.0.0.1:5432`.
`.env`'s `BRAIN_URL` should be `http://127.0.0.1:8000` for local runs.

**VPS (with the Caddy vhost from `compose/Caddyfile` already serving
`brain.{your-domain}`):**
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

If the first run round-trips, Graphiti is wired correctly and the
extraction model is reachable.

### 4. Migrate Notion content (optional)

The migrator is domain-agnostic — point it at any Notion database or page id:

```sh
python migrate/notion_to_graphiti.py --target <notion-id> --kind auto --dry-run
python migrate/notion_to_graphiti.py --target <notion-id> --kind auto
```

`--dry-run` prints the planned episodes without writing. The live run
records each migrated item in `brain.migration_log` (Postgres), so
re-runs only touch items that changed in Notion.

### 5. Wire Claude Code (optional)

See [`templates/claude-code-client/INSTALL.md`](templates/claude-code-client/INSTALL.md)
for how to drop the MCP server entry and the `UserPromptSubmit` memory
injection hook into any of your project repos.
