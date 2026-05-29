# Plan: Phase 1 — Brain online, Claude Code reads it

## Status: stack works end-to-end; remaining work is operator-side

This plan was written before anyone ran the stack end-to-end. The first real smoke (2026-05-25) surfaced a stack of issues — all are now resolved in the repo. The remaining gating items are operator setup (Voyage billing, VPS provisioning, client wiring), not code.

### Resolved during smoke
- **LLM provider routing** — the published `zepai/knowledge-graph-mcp:latest` image ships without the `providers` extra of `mcp_server`, so anthropic/voyage/gemini/groq SDKs aren't installed and the MCP server silently falls back to "no LLM configured." Resolved by building our own image at `compose/graphiti/Dockerfile`, pinned to upstream `v0.29.1`, with `--extra providers --extra azure` installed. Reverts the config to native anthropic + voyage providers.
- **Cross-encoder default** — `graphiti-core.Graphiti.__init__` always instantiates an `OpenAIRerankerClient`, which demands `OPENAI_API_KEY` at construction even when unused. The MCP server doesn't expose a `cross_encoder=` override. Worked around by passing a placeholder `OPENAI_API_KEY` in compose; documented inline.
- **Upstream issue [#1103](https://github.com/getzep/graphiti/issues/1103)** — the MCP server's config schema defaults `temperature` to `None`, which Anthropic's API rejects. Worked around by setting `temperature: 1.0` explicitly in `graphiti-config.yaml`.
- **Image name fix** — the published image is `zepai/knowledge-graph-mcp`, not `zepai/graphiti-mcp` (Zep renamed). Moot now that we build our own, but documented because the upstream plan referenced the old name.
- **Config mount path** — Graphiti reads from `/app/mcp/config/config.yaml`, not `/app/config/config.yaml`. Fixed in compose.
- **MCP session handshake** — streamable-HTTP requires `initialize` → echo back `mcp-session-id` on every subsequent call. Implemented in `migrate/graphiti_clients.py`.
- **Compose `.env` precedence** — Claude Code subshells export empty `ANTHROPIC_API_KEY`, which shadows the file value. Documented in README; the fix is `unset ANTHROPIC_API_KEY` before `docker compose up`.
- **`.env` location** — Compose only auto-loads `compose/.env`, not `./.env.local` at repo root. Documented.

### Open items (operator-side, not code)
- **Voyage payment method** — Free tier without a card is 3 RPM, which blocks even single-episode extraction (entity extraction makes a burst of embedding calls per episode). Add a card on the [Voyage dashboard](https://dashboard.voyageai.com/) to use the 200M free tokens at proper RPS.
- **VPS provisioning (US-004)** — DNS, UFW, Caddy, env vars on the VPS. Not started.
- **Claude Code client wiring** — end-to-end test of `.mcp.json` + the `UserPromptSubmit` hook in a real client repo.
- **Notion seed migration smoke** — dry-run + live-run against a small DB.

See [README → Known limits](../README.md#known-limits--setup-gotchas) for the full writeup.

## Context

Phase 0 left a working VPS substrate (small VPS, Ubuntu LTS, Caddy, UFW, Tailscale). Phase 1 puts the graph on top of it and gives Claude Code in any client repo a way to read from it. End state: ask any question whose answer lives in seeded content from a configured client repo, get a real answer pulled from Graphiti without naming the source or any tool.

**Three workstreams, sequenced:**
1. Provision Graphiti + FalkorDB on the VPS (infra)
2. Migrate seed content into the graph (data)
3. Wire Claude Code to query it (client)

The third workstream depends on the first two. The first two can be parallelized but workstream 1 should land first because it provides the target endpoint workstream 2 writes to.

**Definition of done for Phase 1:** in a configured client repo, prompting Claude Code with a question that depends on seeded content returns the right answer without explicit mention of the source, sourced from the graph via the `UserPromptSubmit` hook.

---

## Workstream A — Provision the brain stack

The compose stack is two services: FalkorDB and Graphiti. Caddy is VPS-only (TLS + bearer) and sits in front of Graphiti. A `docker-compose.local.yml` overlay exposes Graphiti on `127.0.0.1:8000` for laptop development. No second store of any kind — Graphiti is the only persistent service in this phase.

### Task A.1 — Add FalkorDB service to docker-compose

**File:** `compose/docker-compose.yml`

Add service with:
- Image: `falkordb/falkordb:latest`
- Internal-only: no `ports:` mapping. Other services reach it on the docker network at `falkordb:6379`.
- Named volume `falkordb-data` mounted at `/data` for persistence
- Healthcheck: `redis-cli ping`
- Resource limit: `mem_limit: 2g` (FalkorDB is in-memory; cap to leave room for the PWA in Phase 2)

**Verify:** `docker compose up -d falkordb && docker compose exec falkordb redis-cli GRAPH.LIST`. Should return empty list, not error.

### Task A.2 — Add Graphiti core + MCP server services

**File:** `compose/docker-compose.yml`

Single service using the official Graphiti MCP server image (which embeds the core + REST API):
- Image: `zepai/knowledge-graph-mcp:latest` (Zep's published name for the Graphiti MCP server; see [Graphiti MCP repo](https://github.com/getzep/graphiti/tree/main/mcp_server))
- Env vars: `FALKORDB_URI=falkor://falkordb:6379`, `ANTHROPIC_API_KEY` (LLM), `VOYAGE_API_KEY` (embedder), `GRAPHITI_GROUP_ID` (defaults to `brain`)
- Bind-mount `compose/graphiti-config.yaml` at `/app/config/config.yaml` — upstream defaults hardcode `gpt-4o-mini` + OpenAI, so we ship our own to pin `llm.provider=anthropic`/`model=claude-haiku-4-5` and `embedder.provider=voyage`/`model=voyage-3-lite`. Other providers (OpenAI direct, OpenRouter, Ollama) are documented swaps in `.env.example`
- Internal port `8000` exposed only on the docker network as `graphiti:8000` (the local overlay maps it to `127.0.0.1:8000` for laptop dev)
- Depends on `falkordb` (with healthcheck condition)

**Verify:** `docker compose exec graphiti curl -s http://localhost:8000/health`. Should return `{"status":"healthy",...}`.

### Task A.3 — Add Caddy route for `brain.{domain}`

**File:** `compose/Caddyfile`

Block:
```
brain.{$BRAIN_DOMAIN} {
    @authorized header Authorization "Bearer {$BRAIN_BEARER_TOKEN}"
    handle @authorized {
        reverse_proxy graphiti:8000
    }
    handle {
        respond 401
    }
}
```

- TLS auto-issued by Let's Encrypt (Caddy default)
- Bearer token via env (long random, set in `.env`, never committed)
- `BRAIN_DOMAIN` and `BRAIN_BEARER_TOKEN` go into `compose/.env.example` with placeholder values

**Verify:** from laptop, `curl -H "Authorization: Bearer $TOKEN" https://brain.{domain}/health` → 200. Without the header → 401.

### Task A.4 — UFW + DNS sanity check

- Confirm UFW still: `allow 80, 443; deny everything else inbound`
- A-record for `brain.{domain}` → VPS public IP, propagated
- fail2ban jail covers Caddy logs (existing config)

**Verify:** `curl https://brain.{domain}` from laptop succeeds with bearer; without it Caddy returns 401.

### Task A.5 — End-to-end smoke from laptop

`scripts/smoke_brain.py`:
1. Calls `add_memory` via MCP JSON-RPC (`POST /mcp/`, method `tools/call`) with sample text. The Graphiti MCP image is FastMCP, not REST — every operation is a tools/call invocation.
2. Polls `search_nodes` for the expected entity (`add_memory` is fire-and-forget; episodes are server-queued and extraction completes asynchronously). 90s timeout.
3. Asserts the entity is reachable in search results.

**Verify:** entity dedup behaves as expected — a second episode that mentions the same entities (`--second`) links to existing nodes instead of duplicating them.

---

## Workstream B — Generic text/document ingest

The brain's native input is an *episode*: a `(name, body)` pair plus a provenance label. Graphiti's per-write entity extraction does the rest. The Phase 1 ingest surface is therefore deliberately generic — drop arbitrary text or files in, get entities and relations out. Specialized producers (Notion, Slack, email, etc.) are out of scope for Phase 1 and tracked separately under "specialized producers (future)" below.

### Task B.1 — `scripts/ingest.py`

**File:** `scripts/ingest.py`

A single CLI that accepts text from stdin, a file, or a directory and posts `add_memory` for each chunk. All episodes land in the single global Graphiti group (`brain` by default; override with `GRAPHITI_GROUP_ID`).

Surfaces:
```
echo "..."          | scripts/ingest.py                       # stdin → one episode
scripts/ingest.py notes/2026-05-25-meeting.md                 # file → one episode (name = filename stem)
scripts/ingest.py journal/                                    # directory → one episode per file
scripts/ingest.py spec.md --split headings                    # H1/H2 sections each become an episode
cat raw.txt | scripts/ingest.py --name "Journal 2026-05-25"   # explicit name override
scripts/ingest.py path --dry-run                              # print what would be ingested
```

**Verify:** `--dry-run` prints the planned episodes; live runs leave entities visible via `MATCH (n:Entity) RETURN n.name` in the FalkorDB Browser.

### Task B.2 — Ingest smoke

**File:** `scripts/smoke_ingest.py`

Exercises the CLI in an isolated `smoketest` group so it never pollutes the real `brain` graph:
1. Pipes a small string through `ingest.py`
2. Ingests a temp markdown file with `--split headings`
3. Polls `search_nodes` until expected entities appear
4. Wipes the `smoketest` graph at the end (or skips wipe with `--keep`)

**Verify:** exit 0 with a printed entity/fact count; the `brain` graph is unaffected.

### Specialized producers (future — not Phase 1)

When a specific source's structure is worth preserving in a way the generic CLI doesn't capture, a specialized producer can be added under `migrate/` (one file per source). The repo already ships an example: `migrate/notion_to_graphiti.py` for Notion databases/pages.

These are explicitly deprioritized — the bet is that generic text ingest plus per-app HTTP clients (see [README](../README.md#the-vision)) covers the practical surface area. Don't build new producers preemptively; add one only when a concrete consumer needs it.

---

## Workstream C — Wire Claude Code to read the graph

### Task C.1 — Add Graphiti MCP server to a client repo's `.mcp.json`

**File:** `<client-repo>/.mcp.json` (current Claude Code expects MCP servers in `.mcp.json`, not `settings.json`).

Add:
```json
{
  "mcpServers": {
    "graphiti": {
      "type": "http",
      "url": "https://brain.${BRAIN_DOMAIN}/mcp",
      "headers": {
        "Authorization": "Bearer ${BRAIN_BEARER_TOKEN}"
      }
    }
  }
}
```

The `${...}` env var interpolation requires both vars be set in the shell before launching `claude`. Document this in the client repo's `CLAUDE.md`.

**Verify:** new Claude Code session in the client repo, ask "list the available MCP tools" — `mcp__graphiti__search_nodes`, `mcp__graphiti__search_facts`, `mcp__graphiti__add_memory` (and the rest of Graphiti's MCP surface) should appear.

### Task C.2 — `UserPromptSubmit` hook for memory injection

**File:** `templates/claude-code-client/inject_memory.py` (drop into `<client-repo>/.claude/hooks/inject_memory.py`)

Behavior:
1. Read prompt from stdin
2. If `BRAIN_INJECT_SCOPE` is set and the cwd isn't under that path, exit 0; if unset, the hook always runs
3. Call Graphiti `search_nodes(query=prompt, limit=5)` with 800ms timeout
4. If hits returned, emit a `hookSpecificOutput.additionalContext` block prepending:
   ```
   <relevant-memory>
   - Node name: short summary
   - ... (top 5)
   </relevant-memory>
   ```
5. On timeout or error: log to `.claude/logs/inject_memory.log` and exit 0 (degrade silent — the prompt still works without injection)

**Wire it in:** `.claude/settings.json` adds a `UserPromptSubmit` hooks block pointing at `.claude/hooks/inject_memory.py`.

### Task C.3 — End-to-end smoke

Open Claude Code in a configured client repo and ask three questions whose answers depend on seeded content (one factual lookup, one relationship traversal, one document-shaped retrieval). All three should return relevant answers without naming the source or any tool by name. Check `.claude/logs/inject_memory.log` to confirm the hook fired and returned hits.

Also confirm the failure mode: turn the brain off and re-ask one question. The hook should degrade silently (log the timeout, exit 0) and the prompt still executes — the brain is an enhancement, never a hard dependency.

---

## Phase 1 portfolio artifact

Twitter thread + companion blog post on the personal site:

**Title:** "Migrating my second brain to a self-hosted property graph in a weekend"

**Beats:**
1. The problem with document-shaped knowledge stores as a substrate for queries
2. Why a graph, not a vector store (the Hermes-vs-graph table)
3. Why FalkorDB over Neo4j (memory footprint on a single VPS)
4. The migration script: deliberately stateless — one-shot seed, no log
5. First real query that worked — screenshot
6. Lessons + what's next (the PWA)

**Discipline:** ship the artifact before starting Phase 2.

---

## Risks called out

- **Extraction cost surprise.** Watch your provider dashboard during the bulk migration. If a few hundred items cost >$10, reconsider the model choice or batch the calls.
- **MCP transport flakiness.** Graphiti's MCP server is young. If the Claude Code MCP integration is unreliable, the fallback is to call the REST endpoint directly from the hook (the hook becomes the only client, no MCP needed for Phase 1).
- **Entity drift in migration.** First migration pass is when entity dedup either works or fails visibly. Plan to spend an hour eyeballing results and tuning entity hints before declaring Phase 1 done.
