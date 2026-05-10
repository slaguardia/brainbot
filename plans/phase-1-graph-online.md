# Plan: Phase 1 — Brain online, Claude Code reads it

## Context

Phase 0 left a working VPS substrate (Hostinger KVM, Ubuntu 24.04, Postgres 18, Caddy, UFW). Phase 1 puts the graph on top of it and gives Claude Code in the personal repo a way to read from it. End state: ask "what stale tracker entries should I follow up on?" in any personal repo, get a real answer pulled from Graphiti without naming Notion or any tool.

**Three workstreams, sequenced:**
1. Provision Graphiti + FalkorDB on the VPS (infra)
2. Migrate Notion content into the graph (data)
3. Wire Claude Code to query it (client)

The third workstream depends on the first two. The first two can be parallelized but workstream 1 should land first because it provides the target endpoint workstream 2 writes to.

**Definition of done for Phase 1:** in any personal repo, prompting Claude Code with "what's the status of my Acme application?" returns the right answer without explicit Notion mention, sourced from the graph via the `UserPromptSubmit` hook.

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
1. POSTs an `add_episode` to the Graphiti REST endpoint with sample text ("met Alice at Acme on May 9 to discuss the FDE role")
2. Polls until extraction completes
3. GETs `search_nodes` with query "Acme" and verifies the entity exists

**Verify:** entity dedup behaves as expected (re-run with "had coffee with Alice from Acme" → existing Alice + Acme nodes get linked, not duplicated).

---

## Workstream B — Notion → Graphiti migration

### Task B.1 — Migration script skeleton

**New file:** `migrate/notion_to_graphiti.py`

Structure:
```
class NotionMigrator:
    def __init__(self, notion_client, graphiti_client): ...
    def migrate_application_tracker(self): ...
    def migrate_outreach_samples(self): ...
    def migrate_writing_samples(self): ...
    def migrate_my_story(self): ...
    def migrate_outreach_philosophy(self): ...
    def migrate_voice_rules(self): ...

if __name__ == "__main__":
    # CLI: --source <name>|all  --dry-run  --since <date>
```

Each `migrate_*` function:
- Pages through the Notion source
- For each row, builds an episode body + `entity_hints` (e.g., `{"company": "Acme", "role": "FDE", "status": "applied"}`)
- Calls `graphiti.add_episode(name, body, source_description="notion-tracker", reference_time=row.created_at, entity_hints=...)`

### Task B.2 — Idempotency: track migrated rows

**Storage choice:** new Postgres table in `personal.brain` schema:
```sql
CREATE TABLE brain.migration_log (
  source TEXT NOT NULL,         -- 'application_tracker', 'outreach_samples', etc.
  notion_page_id TEXT NOT NULL,
  notion_last_edited TIMESTAMPTZ NOT NULL,
  graphiti_episode_id TEXT NOT NULL,
  migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source, notion_page_id)
);
```

On re-run:
- If `notion_page_id` not in log → migrate, insert row
- If `notion_page_id` in log AND `notion_last_edited > stored value` → re-migrate (Graphiti's bi-temporal handling will invalidate the prior fact), update row
- Otherwise skip

This makes the script safe to re-run after Notion edits.

### Task B.3 — Migrate Application Tracker

**Source:** Notion DB ID for Application Tracker (in user's Notion reference memory)

**Per-row episode shape:**
- `name`: `"Application: {company} — {role} ({status})"`
- `body`: structured paragraph mentioning company, role, source (where you found it), date applied, current status, last touchpoint, notes
- `entity_hints`: `{"company": ..., "role": ..., "status": ...}`

**Verify:** after running, `search_nodes("recent applications")` returns expected companies; `search_facts("applied to FDE roles in May")` returns the right subset.

### Task B.4 — Migrate Outreach Samples

**Source:** Notion DB for Outreach Samples (the per-message database under Writing Samples)

**Per-row episode:**
- `name`: `"Outreach: {persona} at {company} — {channel}"`
- `body`: the full message text + context (why sent, what hooked them, response if any)
- `entity_hints`: `{"company": ..., "person": ..., "persona": ..., "channel": "linkedin|email|twitter"}`

### Task B.5 — Migrate Writing Samples + My Story + Outreach Philosophy + voice rules

These are document-shaped, not row-shaped. One episode per Notion page (or per top-level section if pages are long), with `entity_hints` flagging them as voice/style references so the agent can retrieve them when drafting.

### Task B.6 — Run full migration, audit results

Run with `--dry-run` first, eyeball the log, then live run.

**Audit checklist:**
- Count of episodes per source matches Notion row counts
- Spot-check 5 entities: do `Acme` from tracker, `Acme` from outreach samples, and `Acme` from a journal note all collapse to one node?
- Spot-check 5 facts: do they have correct `valid_from` timestamps?
- Cost: total Anthropic spend for the migration (extraction calls). Should be under $5 for a reasonable Notion size. Record actual.

---

## Workstream C — Wire Claude Code to read the graph

### Task C.1 — Add Graphiti MCP server to `.claude/settings.json`

**File:** `~/Repositories/personal/.claude/settings.json`

Add:
```json
{
  "mcpServers": {
    "graphiti": {
      "url": "https://brain.{your-domain}/mcp",
      "headers": {
        "Authorization": "Bearer ${BRAIN_BEARER_TOKEN}"
      }
    }
  }
}
```

The `${...}` env var interpolation requires the var be set in shell before launching `claude`. Document this in the personal repo's `CLAUDE.md`.

**Verify:** new Claude Code session in `personal/`, ask "list the available MCP tools" — `mcp__graphiti__search_nodes`, `mcp__graphiti__search_facts`, `mcp__graphiti__add_episode` should appear.

### Task C.2 — `UserPromptSubmit` hook for memory injection

**New file:** `~/Repositories/personal/.claude/hooks/inject_memory.py`

Behavior:
1. Read prompt from stdin
2. If working directory is not under `personal/`, exit 0 (do nothing)
3. Embed the prompt (cheap embedding model — `text-embedding-3-small` via OpenAI or use Graphiti's hybrid endpoint)
4. Call Graphiti `search_nodes(query=prompt, limit=5)` with 800ms timeout
5. If hits returned, prepend to the prompt as:
   ```
   <relevant-memory>
   - Acme: senior FDE role applied 2026-04-15, Sarah Lee response pending
   - ... (top 5)
   </relevant-memory>
   ```
6. On timeout or error: log to `.claude/logs/inject_memory.log` and exit 0 (degrade silent — the prompt still works without injection)

**Wire it in:** `.claude/settings.json` adds `hooks: { UserPromptSubmit: [...] }` block.

### Task C.3 — End-to-end smoke

Open Claude Code in `personal/`, ask without any context:
- "what's the latest status on my Acme application?"
- "who did I last DM that responded?"
- "show me the voice rules for outreach"

All three should return relevant answers sourced from the graph. Check `.claude/logs/inject_memory.log` to confirm the hook fired and returned hits.

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

- **Extraction cost surprise.** Watch the Anthropic dashboard during the bulk migration. If a few hundred tracker rows cost >$10, reconsider the model choice or batch the calls.
- **MCP transport flakiness.** Graphiti's MCP server is young. If the Claude Code MCP integration is unreliable, the fallback is to call the REST endpoint directly from the hook (the hook becomes the only client, no MCP needed for Phase 1).
- **Entity drift in migration.** First migration pass is when entity dedup either works or fails visibly. Plan to spend an hour eyeballing results and tuning entity hints before declaring Phase 1 done.
