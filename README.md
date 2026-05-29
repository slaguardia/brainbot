# brainbot

A self-hosted personal knowledge service. **Plug-and-play intelligence for any app you build.**

You dump arbitrary text — work history, preferences, meeting notes, journal entries, anything — into the brain. The brain extracts typed entities and relationships, dedupes them across sources, and exposes them over HTTP/MCP. Then any app you build can consult the brain as ground truth.

Concrete example: dump your work experience + the kind of roles you'd consider into the brain. Build a separate app that fetches job listings from wherever. That app calls the brain to score each listing against what it actually knows about you — without you having to maintain a separate profile or context per app.

Two first-party consumers ship with the project today, both as worked examples:

- **Claude Code MCP** — terminal harness in any project repo. Reads from the brain ambiently via a `UserPromptSubmit` hook; writes session summaries back via `SessionEnd`. (Phase 1.)
- **PWA** — a one-screen mobile capture surface: type a thought, tap send, it lands in the brain in two seconds. Google sign-in + email whitelist, enforced at the edge. (Phase 2.) Graph inspection/editing is done via the FalkorDB Browser, not the PWA.

But these are just two of many possible consumers. The point of the project is the shared brain. Your job-fit scorer, your travel planner, your reading-list app — each one stays small and stateless because the brain holds the cross-app knowledge.

Built on [graphiti-core](https://github.com/getzep/graphiti) (bi-temporal property graph), constructed directly by a small Python **brain service** (no standalone Graphiti MCP server in the loop), backed by [FalkorDB](https://www.falkordb.com), behind Caddy on a small VPS.

## Why this exists

Two reasons:

1. **The bet on shape.** Most personal-AI memory is turn-shaped (chat turns + vector recall). That works for "what did we talk about." It degrades fast for "what people have I talked to about X in the last 30 days." A property graph with bi-temporal facts and entity dedup gives structured queries vectors can't. The cost is an LLM extraction call per write (~$0.0016) and brittleness if extraction drifts.
2. **One brain, many consumers.** The same knowledge backs every app you build. Each consumer stays narrow and dumb; the brain stays the only thing that has to be smart.

The full reasoning lives in [`architecture.md`](./architecture.md). Per-component working docs (current state + tradeoffs + alternatives considered) live in [`docs/`](./docs/README.md).

## Status

| Phase | Status | Detail |
|---|---|---|
| 0 — VPS + Docker substrate | ✅ done | Small VPS, Ubuntu LTS, UFW, Caddy, Tailscale |
| 1 — Brain online + ingest + Claude Code reads it | 🟡 in progress | Stack runs end-to-end locally with native Anthropic + Voyage providers via a custom-built image. Generic text/document ingest CLI is working. Remaining: VPS deployment + Claude Code client wiring. See [`plans/phase-1-graph-online.md`](./plans/phase-1-graph-online.md) and [Known limits](#known-limits--setup-gotchas) below. |
| 2 — PWA: one-screen capture + brain service | 🟡 mostly built | Re-scoped from chat/browse/edit down to a single capture screen (the pivot made the brain the product, not the UI). Shipped the `brain` service + capture PWA + Google edge auth. See [`plans/phase-2-pwa-harness.md`](./plans/phase-2-pwa-harness.md) + [`plans/phase-2-pwa-auth.md`](./plans/phase-2-pwa-auth.md). |
| 3 — Write-back loop + capture polish | 🟡 in plan | [`plans/phase-3-writeback.md`](./plans/phase-3-writeback.md) |
| 4 — Hardening + life expansion | 🟡 in plan | [`plans/phase-4-hardening.md`](./plans/phase-4-hardening.md) |

## The vision

The brain is one self-hosted HTTP service. Anything that wants to act on personal knowledge calls it. Examples worth building once the substrate is solid:

- **Job-fit scorer.** Fetches listings from wherever; queries the brain for relevant work history + preferences; tags each listing as `pursue / skip / maybe` with the matching evidence.
- **Reading queue triage.** Pull in articles from Pocket/RSS; the brain knows what you've already read on each topic and what you actually retained, so the queue surfaces what fills a gap rather than what's recent.
- **Calendar prep.** Before a meeting, the brain looks up everything you've ever captured about the attendees + the project.
- **CRM-as-side-effect.** Every "had coffee with X" episode you drop in becomes a relationship in the graph automatically — no manual data entry.

Each of these is a thin consumer. The intelligence lives in the brain.

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
├── brain/                       — the brain service (FastAPI; constructs graphiti-core directly; capture + recall + MCP face)
├── pwa/                         — Phase 2 one-screen capture PWA (thin proxy to the brain)
├── compose/                     — docker-compose, Caddyfile, oauth2-proxy whitelist
├── scripts/
│   ├── ingest.py                — drop arbitrary text or files into the brain as episodes (primary surface)
│   ├── smoke_brain.py           — brain API contract smoke (capture → recall)
│   ├── smoke_ingest.py          — ingest CLI smoke
│   └── reset_brain.py           — wipe a graph (defaults to the smoketest graph; safe)
├── migrate/                     — specialized producers when a source needs special handling (rare)
│   └── notion_to_graphiti.py    — historical example; not actively developed
└── templates/
    └── claude-code-client/      — drop-in MCP config + UserPromptSubmit hook for any project repo
```


## Running it (fresh install)

The stack is two compose services: `falkordb` (graph store) and `brain` (a FastAPI service that constructs graphiti-core directly and does the decompose + entity-extraction pipeline on every write). On the VPS, Caddy adds two vhosts — `brain.api.{domain}` (the brain API, bearer-authed) and `brain.{domain}` (the PWA, Google sign-in via oauth2-proxy). No second store — FalkorDB is the only persistent service.

### 1. Configure env

```sh
cd compose
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (LLM extraction + decomposition) and
# VOYAGE_API_KEY (embeddings) — the brain reads these directly (see brain/config.py).
# For the VPS also set BRAIN_DOMAIN, BRAIN_BEARER_TOKEN, the Google OAuth client
# vars + OAUTH2_PROXY_COOKIE_SECRET (PWA auth), and NOTION_TOKEN if you'll run the migrator.
#
# Voyage: you'll need a payment method on https://dashboard.voyageai.com/
# even though Phase 1 fits inside the 200M-token free allowance. Without
# a card, free-tier rate limits (3 RPM) block extraction itself. See
# Known limits below.
#
# Heads-up: if your shell already exports ANTHROPIC_API_KEY="" (Claude
# Code subshells do this), Compose will read the empty value and ignore
# your .env. `unset ANTHROPIC_API_KEY` before `docker compose up`.
```

### 2. Bring the stack up

**Local laptop (no Caddy, no TLS, port exposed on 127.0.0.1):**
```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
docker compose ps                       # both healthy?
```

The `brain` service is at `http://127.0.0.1:8100` (the local overlay exposes it on the host; it also exposes the FalkorDB Browser at `http://127.0.0.1:3000`). `.env`'s `BRAIN_URL` should be `http://127.0.0.1:8100` for local runs.

**VPS (with the Caddy vhosts from `compose/Caddyfile` already serving `brain.api.{your-domain}` + `brain.{your-domain}`):**
```sh
docker compose up -d
docker compose ps
```

`.env`'s `BRAIN_URL` should be `https://brain.api.your-domain.com` (the API host; the bare `brain.` host is the Google-auth'd PWA).

### 3. Smoke tests

Two smokes, both isolated to a separate `smoketest` graph so they never touch your real `brain`:

```sh
# Brain API smoke (capture → recall)
python scripts/smoke_brain.py

# Ingest CLI smoke (stdin, file, --split headings, dry-run)
python scripts/smoke_ingest.py
```

> **Heads-up:** these smoke scripts (and `ingest.py`, `migrate/notion_to_graphiti.py`) still target the retired Graphiti tool surface (`add_memory`/`search_nodes`) and a `group_id`-parameterized API. They're being migrated to the brain's `capture`/`recall` contract — see the [reference client](./migrate/graphiti_clients.py) for the current shape.

Both wipe the `smoketest` graph on success unless you pass `--keep`. The FalkorDB Browser graph dropdown will show `smoketest` while a smoke is running and the `brain` graph (your real data) untouched. The unusual graph name (no hyphen) is forced by RediSearch — `-` is the NOT operator in queries.

### 4. Drop content in

The native input is text. Anything can be an episode — paste a journal entry, drop a markdown doc, pipe a meeting transcript. The ingest CLI handles the mechanics:

```sh
# stdin → one episode
echo "Met Beatrice at Globex. She's their new VP platform." | python scripts/ingest.py

# single file → one episode (name = filename stem)
python scripts/ingest.py notes/2026-05-25-meeting.md

# directory → one episode per file
python scripts/ingest.py journal/

# long markdown → split on H1/H2 into separate episodes
python scripts/ingest.py docs/spec.md --split headings

# preview without writing
python scripts/ingest.py notes/ --dry-run
```

Entities, relations, and bi-temporal facts get extracted automatically. You don't tell the brain what's important — it figures that out from the content.

**Specialized sources (rare; deprioritized).** When a specific source has structure worth preserving in a way the generic CLI can't (e.g., Notion database row → episode-per-row with property labels), it can live as a sibling file under `migrate/`. The repo ships one historical example, `migrate/notion_to_graphiti.py`, but the working assumption is that generic ingest + per-app HTTP clients covers the practical surface. Don't build new producers preemptively.

### 5. Wire Claude Code (optional)

See [`templates/claude-code-client/INSTALL.md`](templates/claude-code-client/INSTALL.md) for how to drop the MCP server entry and the `UserPromptSubmit` memory injection hook into any of your project repos. This is the canonical example of "a consumer app talking to the brain over HTTP/MCP."

### 6. Building your own consumer

The brain exposes a small contract — `capture`, `recall`, `profile` — over **plain HTTP/JSON** (`POST /capture`, `GET /recall`, `GET /profile`). Any app — Python, TypeScript, a shell script — can hit it with a bearer token over HTTPS at `brain.api.{domain}`; no protocol library needed. The same three operations are also exposed as **MCP tools** at `/mcp` for Claude Code and other LLM-tool-discovery harnesses. See [`docs/consumer-integration.md`](./docs/consumer-integration.md) and the reference client `migrate/graphiti_clients.py` (`BrainClient`); full spec in [`docs/consumer-api.md`](./docs/consumer-api.md).

The brain doesn't enforce any schema on you — your job-fit scorer and your reading-list app can both query "what does the brain know about Acme" and get back the same Acme entity with the same dedupe'd context. That's the whole point.

## Known limits + setup gotchas

These were all surfaced the first time someone (me) actually ran the Phase 1 smoke end-to-end against a clean machine. Calling them out so you can decide before investing time.

### graphiti-core is pip-installed, not a prebuilt image

Earlier iterations ran Zep's standalone Graphiti MCP server (`zepai/knowledge-graph-mcp:latest`), which was unusable: it ships without the provider extras, so the Anthropic/Voyage SDKs aren't present and it silently falls back to "no LLM configured" for any non-OpenAI provider. That whole class of problem is gone. The `brain` service pip-installs `graphiti-core[anthropic,falkordb,voyageai]==0.29.1` (pinned in `brain/pyproject.toml`) and constructs graphiti-core itself — the provider SDKs are always present, and there's no standalone MCP image or `graphiti-config.yaml` to build or mount. Model/provider settings live in `brain/config.py` (overridable via env; see `brain/README.md`).

**One graphiti-core wrinkle still applies:** `Graphiti.__init__` instantiates an `OpenAIRerankerClient` cross-encoder that demands `OPENAI_API_KEY` at construction time even if you never invoke reranked search. `compose/.env` passes a placeholder so init succeeds; set a real key only if you turn on reranked search.

### `.env` location + shell env shadow (both structurally addressed)

Two related Compose footguns we hit:
- Compose only auto-loads `.env` from the **same directory as the compose file** (`compose/.env`, not the repo root `.env.local`).
- Compose's `${VAR}` interpolation reads the shell environment *before* `.env`, and treats an empty shell value as authoritative — so Claude Code's `ANTHROPIC_API_KEY=""` shell export shadows the real key in `.env` and the container ends up with no key.

Both are sidestepped by using `env_file: .env` (which loads `.env` directly into the container env, bypassing shell interpolation entirely) — which is what our compose now does. **One caveat:** `docker compose restart` does *not* reload `env_file`. Only `down && up` does. If you edit `.env`, full-recreate.

### FalkorDB volume mount + save policy

Two related FalkorDB persistence gotchas:
- The image's `FALKORDB_DATA_PATH` is `/var/lib/falkordb/data`. There's a `/data → /var/lib/falkordb/data` symlink for convenience, but if you mount a volume at `/data` you're overlaying the symlink itself, not the data dir — writes go to the container's ephemeral filesystem and disappear on restart. Mount at `/var/lib/falkordb/data` directly.
- Redis default save thresholds (10K changes / 60s) never fire on a Phase 1-sized dataset, so even with the right mount, data doesn't get snapshotted before shutdown. Our compose passes explicit `--save 30 1` and `--appendonly yes` to force persistence.

### Graph naming: `group_id` *is* the FalkorDB graph name

graphiti-core uses the configured **`group_id`** as the FalkorDB graph name. The brain sets it via `BRAIN_GROUP_ID` (default `brain`), so your data lives in the `brain` graph. When poking around in the FalkorDB Browser, pick the graph that matches `group_id`.

### RediSearch reserves `-` (smoke graph naming)

You'd think a `smoke-test` group_id would be fine. It isn't — graphiti-core runs the group_id through a RediSearch query, where `-` is the NOT operator. The episode silently fails to extract with `RediSearch: Syntax error at offset N near smoke`. Keep group_ids alphanumeric (our smoke uses `smoketest`).

### Voyage requires a payment method on file to run even the smoke test

Voyage's free tier gives you 200M tokens/month free — but without a payment method on file, you're also rate-limited to **3 RPM / 10K TPM**. That sounds generous; it isn't. Entity extraction makes a burst of embedding calls per episode (one per chunk / candidate entity), and a single `capture` (which writes the body + N fact episodes) blows past 3 RPM in under a second. The smoke script's slower poll interval helps with our client-side search calls but does nothing for the server-side extraction pipeline.

**You will need to add a card on the [Voyage dashboard](https://dashboard.voyageai.com/) before any episode actually extracts successfully.** The 200M free tokens are still free — the card just lifts the throttle. Expected real cost for Phase 1 sanity-checking is in the cents.

If you prefer not to use Voyage at all, set `BRAIN_EMBED_MODEL` to a different provider's model — `graphiti-core[openai]` and `graphiti-core[gemini]` extras are available (add them in `brain/pyproject.toml`).

### Other things that bit us once

- The MCP streamable-HTTP endpoint is `/mcp` (no trailing slash). Clients must initialize a session via an `initialize` JSON-RPC call before any tool call — the returned `mcp-session-id` header has to be echoed on every subsequent request. Our `migrate/graphiti_clients.py` does this; if you write a new client, mirror that pattern.
- `scripts/smoke_brain.py` and `migrate/notion_to_graphiti.py` need `requests` (not yet pinned in a `requirements.txt`).
- The first `docker compose up` will trigger a multi-minute image build (`uv sync` downloads the Python dep tree). Subsequent ups reuse the cached layer.
