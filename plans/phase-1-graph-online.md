# Plan: Phase 1 — Brain online, Claude Code reads it

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
- Image: `zepai/graphiti-mcp:latest` (verify exact tag against [Graphiti MCP repo](https://github.com/getzep/graphiti/tree/main/mcp_server))
- Env vars: `FALKORDB_URI=falkor://falkordb:6379`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` (default OpenRouter), `MODEL_NAME` (e.g. `anthropic/claude-haiku-4.5`). Provider-neutral via the OpenAI-compatible API so downstream users can plug in OpenAI direct, Together, Groq, local Ollama, etc.
- Internal port `8000` exposed only on the docker network as `graphiti:8000` (the local overlay maps it to `127.0.0.1:8000` for laptop dev)
- Depends on `falkordb` (with healthcheck condition)

**Verify:** `docker compose exec graphiti curl -s http://localhost:8000/healthz`. Should return 200.

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

**Verify:** from laptop, `curl -H "Authorization: Bearer $TOKEN" https://brain.{domain}/healthz` → 200. Without the header → 401.

### Task A.4 — UFW + DNS sanity check

- Confirm UFW still: `allow 80, 443; deny everything else inbound`
- A-record for `brain.{domain}` → VPS public IP, propagated
- fail2ban jail covers Caddy logs (existing config)

**Verify:** `curl https://brain.{domain}` from laptop succeeds with bearer; without it Caddy returns 401.

### Task A.5 — End-to-end smoke from laptop

`scripts/smoke_brain.py`:
1. POSTs an `add_episode` to the Graphiti REST endpoint with sample text
2. Polls until extraction completes
3. GETs `search_nodes` with a query covering one of the extracted entities and verifies the entity exists

**Verify:** entity dedup behaves as expected — a second episode that mentions the same entities (`--second`) links to existing nodes instead of duplicating them.

---

## Workstream B — Seed → Graphiti migration

The migrator is intentionally domain-agnostic: point it at any Notion database or page id and it produces episodes. Graphiti's per-write entity extraction handles routing/dedup, so the script never needs to know the shape of your data. If your data has structure worth preserving differently, fork `migrate_database` / `migrate_page` directly — the extension point is the source.

Notion is the first source we ship a migrator for because it's the most common seed corpus, but the migrator's contract is generic: anything that can produce `{ name, body, reference_time }` payloads can become a Graphiti episode.

### Task B.1 — Generic migration skeleton

**New file:** `migrate/notion_to_graphiti.py`

Structure:
```
class NotionMigrator:
    def __init__(self, notion_client, graphiti_client, log=None, dry_run=False, since=None): ...
    def migrate_database(self, database_id): ...
    def migrate_page(self, page_id): ...
    def migrate(self, target_id, kind="auto"): ...   # dispatches by kind

if __name__ == "__main__":
    # CLI: --target <notion-id>  --kind {database,page,auto}  --dry-run  --since <date>
```

Each `migrate_*` method:
- Pages through Notion content via the shared `NotionClient`
- For each item, builds an `add_episode` payload (`name`, `body`, `reference_time`)
- Hands the payload to the shared dispatcher

`kind="auto"` peeks at the Notion object to pick `database` or `page` automatically.

The migrator is a one-shot seed. It does not track what's already been written, and there is no migration log. Re-running posts everything again — Graphiti's bi-temporal extraction means re-runs link to existing entities rather than silently fragmenting, but each re-run still pays the extraction cost. If incremental re-runs become important enough to justify state, add tracking then; not preemptively.

### Task B.2 — Generic database migration

**Default shape per row:**
- `name`: the row's title property if present, otherwise `"{database label or id} row {created_time}"`
- `body`: every property flattened as `Property Name: value` lines, in the order Notion returns them
- `reference_time`: `row.created_time`
- `entity_hints`: empty

**Verify:** `--target <db-id> --kind database --dry-run` prints planned episodes for every row in the database.

### Task B.3 — Generic page migration

**Default shape per page:**
- If the page has `heading_2` blocks → emit one episode per H2 section, named `"{page title} - {section heading}"`
- Else → emit one episode for the whole page, named with the page title
- `body`: plain-text concatenation of paragraphs, headings, lists, quotes
- `reference_time`: `page.created_time`

**Verify:** `--target <page-id> --kind page --dry-run` prints one or many episodes depending on whether the page has H2s.

### Task B.4 — Run a migration, audit results

Run with `--dry-run` first, eyeball the log, then live run.

**Audit checklist:**
- Episode count for the chosen target matches Notion item count
- Spot-check entity dedup: an entity referenced in 3+ episodes collapses to one node
- Spot-check fact timestamps: `valid_from` matches the source item's `created_time`
- Cost: total extraction-LLM spend for the run. Surface the actual figure in the audit note.

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

**Verify:** new Claude Code session in the client repo, ask "list the available MCP tools" — `mcp__graphiti__search_nodes`, `mcp__graphiti__search_facts`, `mcp__graphiti__add_episode` should appear.

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
