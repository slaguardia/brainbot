# Plan: Phase 1 — Brain online, Claude Code reads it

## Context

Phase 0 left a working VPS substrate (Hostinger KVM, Ubuntu 24.04, Postgres 18, Caddy, UFW). Phase 1 puts the graph on top of it and gives Claude Code in any client repo a way to read from it. End state: ask any question whose answer lives in migrated Notion content from a configured client repo, get a real answer pulled from Graphiti without naming Notion or any tool.

**Three workstreams, sequenced:**
1. Provision Graphiti + FalkorDB on the VPS (infra)
2. Migrate Notion content into the graph (data)
3. Wire Claude Code to query it (client)

The third workstream depends on the first two. The first two can be parallelized but workstream 1 should land first because it provides the target endpoint workstream 2 writes to.

**Definition of done for Phase 1:** in a configured client repo, prompting Claude Code with a question that depends on migrated content returns the right answer without explicit Notion mention, sourced from the graph via the `UserPromptSubmit` hook.

---

## Workstream A — Provision Graphiti + FalkorDB on the VPS

### Task A.1 — Add FalkorDB service to docker-compose

**File:** `compose/docker-compose.yml` (existing)

Add service with:
- Image: `falkordb/falkordb:latest`
- Internal-only: no `ports:` mapping. Other services reach it on the docker network at `falkordb:6379`.
- Named volume `falkordb-data` mounted at `/data` for persistence
- Healthcheck: `redis-cli ping`
- Resource limit: `mem_limit: 2g` (FalkorDB is in-memory; cap to leave room for Postgres + PWA)

**Verify:** `docker compose up -d falkordb && docker compose exec falkordb redis-cli GRAPH.LIST`. Should return empty list, not error.

### Task A.2 — Add Graphiti core + MCP server services

**File:** `compose/docker-compose.yml`

Single service using the official Graphiti MCP server image (which embeds the core + REST API):
- Image: `zepai/graphiti-mcp:latest` (verify exact tag against [Graphiti MCP repo](https://github.com/getzep/graphiti/tree/main/mcp_server))
- Env vars: `FALKORDB_URI=falkor://falkordb:6379`, `OPENAI_API_KEY` *or* `ANTHROPIC_API_KEY` (depending on extraction model), `MODEL_NAME` (e.g. `claude-haiku-4-5`)
- Internal port `8000` exposed only on the docker network as `graphiti:8000`
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

**Verify:** `curl https://brain.{domain}` from laptop succeeds; from a non-allowlisted source still resolves but Caddy returns 401 without bearer.

### Task A.5 — End-to-end smoke from laptop

Write a one-off Python or curl script that:
1. POSTs an `add_episode` to the Graphiti REST endpoint with sample text ("met Alice at Acme on May 9 to discuss the engineering role")
2. Polls until extraction completes
3. GETs `search_nodes` with query "Acme" and verifies the entity exists

**Verify:** entity dedup behaves as expected (re-run with "had coffee with Alice from Acme" → existing Alice + Acme nodes get linked, not duplicated).

---

## Workstream B — Notion → Graphiti migration

The migrator is intentionally domain-agnostic: point it at any Notion database or page id and it produces episodes. Graphiti's per-write entity extraction handles routing/dedup, so the headline path doesn't need hand-coded shapes for any specific source. Domain shaping is opt-in through the recipes hook.

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
    # CLI: --target <notion-id>  --kind {database,page,auto}  --dry-run  --since <date>  [--recipe <module:function>]
```

Each `migrate_*` method:
- Pages through Notion content via the shared `NotionClient`
- For each item, builds an `add_episode` payload (`name`, `body`, `reference_time`, `notion_page_id`, `notion_last_edited`)
- Hands the payload to a shared dispatcher that consults the migration log (B.2) before posting

`kind="auto"` peeks at the Notion object to pick `database` or `page` automatically.

### Task B.2 — Idempotency: track migrated items

**Storage choice:** new Postgres table in the `brain` schema:
```sql
CREATE TABLE brain.migration_log (
  notion_page_id      TEXT        NOT NULL PRIMARY KEY,
  target_id           TEXT        NOT NULL,         -- the database/page id passed on the CLI
  notion_last_edited  TIMESTAMPTZ NOT NULL,
  graphiti_episode_id TEXT        NOT NULL,
  migrated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

On re-run:
- If `notion_page_id` not in log → migrate, insert row
- If `notion_page_id` in log AND `notion_last_edited > stored value` → re-migrate (Graphiti's bi-temporal handling invalidates the prior fact), update row
- Otherwise skip

This makes the script safe to re-run after Notion edits.

### Task B.3 — Generic database migration

**Default shape per row:**
- `name`: the row's title property if present, otherwise `"{database label or id} row {created_time}"`
- `body`: every property flattened as `Property Name: value` lines, in the order Notion returns them
- `reference_time`: `row.created_time`
- `entity_hints`: empty (recipes layer adds them when the operator opts in)

**Verify:** `--target <db-id> --kind database --dry-run` prints planned episodes for every row in the database.

### Task B.4 — Generic page migration

**Default shape per page:**
- If the page has `heading_2` blocks → emit one episode per H2 section, named `"{page title} - {section heading}"`
- Else → emit one episode for the whole page, named with the page title
- `body`: plain-text concatenation of paragraphs, headings, lists, quotes
- `reference_time`: `page.created_time`

**Verify:** `--target <page-id> --kind page --dry-run` prints one or many episodes depending on whether the page has H2s.

### Task B.5 — Recipes hook for opt-in domain shapes

Domain-aware ingestion lives outside the headline API:

- `migrate/recipes/` ships with a `__init__.py`, a `README.md` explaining the contract, and at least one example recipe
- Recipe contract: `recipe(item, context) -> PlannedEpisode | list[PlannedEpisode] | None`
  - `item` is the Notion row dict (database mode) or page dict (page mode)
  - `context` exposes `notion_client`, `target_id`, `kind`, `dry_run`
  - Return `None` to fall back to the generic shape
- CLI flag `--recipe <module:function>` lets the operator override per run; without it, the generic shape is used
- No domain-specific recipes ship in the repo. Operators with structured Notion data can write a private recipe in their own fork.

### Task B.6 — Run a migration, audit results

Run with `--dry-run` first, eyeball the log, then live run.

**Audit checklist:**
- Episode count for the chosen target matches Notion item count
- Spot-check entity dedup: an entity referenced in 3+ episodes collapses to one node
- Spot-check fact timestamps: `valid_from` matches the source item's `created_time`
- Cost: total Anthropic spend for the run (extraction calls). Surface the actual figure in the audit note.

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

**New file:** `<client-repo>/.claude/hooks/inject_memory.py`

Behavior:
1. Read prompt from stdin
2. If `BRAIN_INJECT_SCOPE` is set and the cwd isn't under that path, exit 0; if unset, the hook always runs
3. Embed the prompt (cheap embedding model — `text-embedding-3-small` via OpenAI or use Graphiti's hybrid endpoint)
4. Call Graphiti `search_nodes(query=prompt, limit=5)` with 800ms timeout
5. If hits returned, prepend to the prompt as:
   ```
   <relevant-memory>
   - Node name: short summary
   - ... (top 5)
   </relevant-memory>
   ```
6. On timeout or error: log to `.claude/logs/inject_memory.log` and exit 0 (degrade silent — the prompt still works without injection)

**Wire it in:** `.claude/settings.json` adds `hooks: { UserPromptSubmit: [...] }` block.

### Task C.3 — End-to-end smoke

Open Claude Code in a configured client repo and ask three questions whose answers depend on migrated content (one factual lookup, one relationship traversal, one document-shaped retrieval). All three should return relevant answers without naming Notion or any tool by name. Check `.claude/logs/inject_memory.log` to confirm the hook fired and returned hits.

Also confirm the failure mode: turn the brain off and re-ask one question. The hook should degrade silently (log the timeout, exit 0) and the prompt still executes — the brain is an enhancement, never a hard dependency.

---

## Phase 1 portfolio artifact

Twitter thread + companion blog post on the personal site:

**Title:** "Migrating my second brain from Notion to a self-hosted property graph in a weekend"

**Beats:**
1. The problem with Notion as substrate (great editor, terrible substrate for queries)
2. Why a graph, not a vector store (the Hermes-vs-graph table)
3. Why FalkorDB over Neo4j (memory footprint on a single VPS)
4. The migration script: idempotency-via-Postgres-log was the unlock
5. First real query that worked — screenshot
6. Lessons + what's next (the PWA)

**Discipline:** ship the artifact before starting Phase 2.

---

## Risks called out

- **Extraction cost surprise.** Watch the Anthropic dashboard during the bulk migration. If a few hundred Notion items cost >$10, reconsider the model choice or batch the calls.
- **MCP transport flakiness.** Graphiti's MCP server is young. If the Claude Code MCP integration is unreliable, the fallback is to call the REST endpoint directly from the hook (the hook becomes the only client, no MCP needed for Phase 1).
- **Entity drift in migration.** First migration pass is when entity dedup either works or fails visibly. Plan to spend an hour eyeballing results and tuning entity hints before declaring Phase 1 done.
