# brainbot

A self-hosted personal knowledge service. **Plug-and-play intelligence for any app you build.**

You dump arbitrary text — work history, preferences, meeting notes, journal entries, anything — into the brain. The brain extracts typed entities and relationships, dedupes them across sources, and exposes them over HTTP/MCP. Then any app you build can consult the brain as ground truth.

Concrete example: dump your work experience + the kind of roles you'd consider into the brain. Build a separate app that fetches job listings from wherever. That app calls the brain to score each listing against what it actually knows about you — without you having to maintain a separate profile or context per app.

Two first-party consumers ship with the project today, both as worked examples:

- **Claude Code MCP** — terminal harness in any project repo. Reads from the brain ambiently via a `UserPromptSubmit` hook; writes session summaries back via `SessionEnd`. (Phase 1.)
- **PWA** — phone + desktop surface for direct human use: chat, browse/edit the graph, capture thoughts in two seconds. (Phase 2, planned.)

But these are just two of many possible consumers. The point of the project is the shared brain. Your job-fit scorer, your travel planner, your reading-list app — each one stays small and stateless because the brain holds the cross-app knowledge.

Built on [Graphiti](https://github.com/getzep/graphiti) (bi-temporal property graph) backed by [FalkorDB](https://www.falkordb.com), behind Caddy on a small VPS.

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
| 2 — PWA: chat + browse/edit + capture | 🟡 in plan, may be re-scoped | [`plans/phase-2-pwa-harness.md`](./plans/phase-2-pwa-harness.md) — the pivot toward "brain as service for many apps" may reduce what the PWA needs to do. |
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
├── compose/                     — docker-compose, Dockerfile (custom Graphiti image), Caddyfile
├── scripts/
│   ├── ingest.py                — drop arbitrary text or files into the brain as episodes (primary surface)
│   ├── smoke_brain.py           — brain API contract smoke (add_memory → search → dedup)
│   ├── smoke_ingest.py          — ingest CLI smoke
│   └── reset_brain.py           — wipe a graph (defaults to the smoketest graph; safe)
├── migrate/                     — specialized producers when a source needs special handling (rare)
│   └── notion_to_graphiti.py    — historical example; not actively developed
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

`graphiti` is at `http://127.0.0.1:8000`. `.env`'s `BRAIN_URL` should be `http://127.0.0.1:8000` for local runs.

**VPS (with the Caddy vhost from `compose/Caddyfile` already serving `brain.{your-domain}`):**
```sh
docker compose up -d
docker compose ps
```

`.env`'s `BRAIN_URL` should be `https://brain.your-domain.com`.

### 3. Smoke tests

Two smokes, both isolated to a separate `smoketest` graph so they never touch your real `brain`:

```sh
# Brain API smoke (add_memory → search_nodes → optional dedup)
python scripts/smoke_brain.py            # post episode + verify node
python scripts/smoke_brain.py --dedup    # also post a follow-up + assert no dup nodes

# Ingest CLI smoke (stdin, file, --split headings, dry-run)
python scripts/smoke_ingest.py
```

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

The brain exposes its operations over **MCP JSON-RPC** at `/mcp` (the same endpoint Claude Code talks to). Any app — Python, TypeScript, a shell script — can hit it with a bearer token over HTTPS. The two tools you'll use 90% of the time are `search_nodes` (find entities matching a query) and `search_memory_facts` (find typed facts). See `migrate/graphiti_clients.py` for a minimal Python client doing the JSON-RPC + session handshake; reuse it from your own apps or port the pattern.

The brain doesn't enforce any schema on you — your job-fit scorer and your reading-list app can both query "what does the brain know about Acme" and get back the same Acme entity with the same dedupe'd context. That's the whole point.

## Known limits + setup gotchas

These were all surfaced the first time someone (me) actually ran the Phase 1 smoke end-to-end against a clean machine. Calling them out so you can decide before investing time.

### We build our own Graphiti MCP image (don't use `zepai/knowledge-graph-mcp:latest`)

Upstream Zep publishes a Docker image at `zepai/knowledge-graph-mcp:latest`, and the upstream Phase 1 plan originally pointed at it. **We can't use it.** It ships with the `providers` extra of `mcp_server` omitted, so the anthropic / voyage / gemini / groq SDKs aren't installed inside the container, and the MCP server silently falls back to "no LLM configured" for any non-OpenAI provider. Startup logs it explicitly:

```
Failed to create LLM client: Anthropic client not available in current graphiti-core version
```

Beyond that, the image's factory (`/app/mcp/src/services/factories.py`) constructs the OpenAI LLM client without plumbing the configured `api_url` through, so even the "point openai at Anthropic's OAI-compat endpoint" workaround doesn't work — and the OpenAI client uses `client.responses.parse()` for structured completions, which is OpenAI-only anyway.

**What we do instead:** `compose/graphiti/Dockerfile` builds our own image from upstream's source at a pinned tag (`v0.29.1`), installing `mcp_server` with `--extra providers --extra azure`. This is literally what upstream's own `Dockerfile.standalone` does — the published image just isn't built from it (or is stale). `docker-compose.yml` references this build context, so the image is built locally on first `docker compose up`.

**Extra wrinkle worked around:** `graphiti-core`'s `Graphiti.__init__` always instantiates an `OpenAIRerankerClient` cross-encoder for search reranking, which demands `OPENAI_API_KEY` at construction time even when it's never invoked. The MCP server doesn't expose a `cross_encoder=` override. Compose passes a placeholder `OPENAI_API_KEY` to let init succeed; the reranker won't be called unless you explicitly invoke reranked search. If/when you do, set a real key.

**Tracking upstream:** We pin `GRAPHITI_REF` in `compose/docker-compose.yml`. Bump it when upstream cuts a release that includes a relevant fix. The known-relevant open issue is upstream [#1103](https://github.com/getzep/graphiti/issues/1103) — the MCP server's config schema defaults `temperature` to `None`, which Anthropic's API rejects with HTTP 400. Our `compose/graphiti-config.yaml` sets `temperature: 1.0` explicitly to dodge it.

### `.env` location + shell env shadow (both structurally addressed)

Two related Compose footguns we hit:
- Compose only auto-loads `.env` from the **same directory as the compose file** (`compose/.env`, not the repo root `.env.local`).
- Compose's `${VAR}` interpolation reads the shell environment *before* `.env`, and treats an empty shell value as authoritative — so Claude Code's `ANTHROPIC_API_KEY=""` shell export shadows the real key in `.env` and the container ends up with no key.

Both are sidestepped by using `env_file: .env` (which loads `.env` directly into the container env, bypassing shell interpolation entirely) — which is what our compose now does. **One caveat:** `docker compose restart` does *not* reload `env_file`. Only `down && up` does. If you edit `.env`, full-recreate.

### FalkorDB volume mount + save policy

Two related FalkorDB persistence gotchas:
- The image's `FALKORDB_DATA_PATH` is `/var/lib/falkordb/data`. There's a `/data → /var/lib/falkordb/data` symlink for convenience, but if you mount a volume at `/data` you're overlaying the symlink itself, not the data dir — writes go to the container's ephemeral filesystem and disappear on restart. Mount at `/var/lib/falkordb/data` directly.
- Redis default save thresholds (10K changes / 60s) never fire on a Phase 1-sized dataset, so even with the right mount, data doesn't get snapshotted before shutdown. Our compose passes explicit `--save 30 1` and `--appendonly yes` to force persistence.

### Graphiti graph naming: `group_id`, not the configured `database`

`graphiti-config.yaml` has a `database.providers.falkordb.database` field that looks like it should name the FalkorDB graph. It doesn't — Graphiti uses the configured **`group_id`** as the graph name. (Our brain is in the `brain` graph because `GRAPHITI_GROUP_ID=brain`, even though `database` says `default_db`.) When poking around in the FalkorDB Browser, pick the graph that matches `group_id`.

### RediSearch reserves `-` (smoke graph naming)

You'd think a `smoke-test` group_id would be fine. It isn't — Graphiti runs the group_id through a RediSearch query, where `-` is the NOT operator. The episode silently fails to extract with `RediSearch: Syntax error at offset N near smoke`. Keep group_ids alphanumeric (our smoke uses `smoketest`).

### Voyage requires a payment method on file to run even the smoke test

Voyage's free tier gives you 200M tokens/month free — but without a payment method on file, you're also rate-limited to **3 RPM / 10K TPM**. That sounds generous; it isn't. Graphiti's entity extraction makes a burst of embedding calls per episode (one per chunk / candidate entity), and a single `add_memory` call blows past 3 RPM in under a second. The smoke script's slower poll interval helps with our client-side search calls but does nothing for the server-side extraction pipeline.

**You will need to add a card on the [Voyage dashboard](https://dashboard.voyageai.com/) before any episode actually extracts successfully.** The 200M free tokens are still free — the card just lifts the throttle. Expected real cost for Phase 1 sanity-checking is in the cents.

If you prefer not to use Voyage at all, swap the embedder in `compose/graphiti-config.yaml` — `graphiti-core[openai]` and `graphiti-core[gemini]` are both supported by our custom image build.

### Other things that bit us once

- Graphiti's config path inside the container is `/app/mcp/config/config.yaml`, not `/app/config/config.yaml`. Bind-mount target matters.
- The MCP streamable-HTTP endpoint is `/mcp` (no trailing slash). Clients must initialize a session via an `initialize` JSON-RPC call before any tool call — the returned `mcp-session-id` header has to be echoed on every subsequent request. Our `migrate/graphiti_clients.py` does this; if you write a new client, mirror that pattern.
- `scripts/smoke_brain.py` and `migrate/notion_to_graphiti.py` need `requests` (not yet pinned in a `requirements.txt`).
- The first `docker compose up` will trigger a multi-minute image build (`uv sync` downloads the Python dep tree). Subsequent ups reuse the cached layer.
