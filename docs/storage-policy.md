# Storage policy

Graphiti (FalkorDB) is the **only persistent store** in Phases 1–3. No Postgres, no SQLite, no relational anything.

## What this means concretely

- **Migration log:** none. The Notion → Graphiti migrator is a one-shot seed. Re-runs re-post everything — Graphiti's bi-temporal handling means re-runs link to existing entities rather than silently fragmenting, but each re-run pays the extraction cost.
- **Capture queue:** none in Phase 2. Captures are synchronous (1–3s wait for extraction). Phase 3 introduces an in-memory queue when the iOS Shortcut surface forces sub-100ms response. Even then: in-memory only, no persistent spool. Crash means losing in-flight captures, accepted as a personal-use tradeoff.
- **Tool-call observability:** stderr logs in Phase 2. `docker logs pwa` is the dashboard. A real `/admin` UI is a Phase 4 task that explicitly punts the store choice ("default to rotated ndjson; reach for SQLite only if structured queries become necessary").

## Why no second store

Every persistent store is a decision a downstream user has to inherit — schema migrations, backup story, connection pooling, version pinning, ops surface area. Deferring the decision until the data shape is obvious means picking the right store later, not the most-capable store now.

The five "needs" earlier passes were trying to solve (drafts, tool calls, migration log, pending episodes, dedup candidates) are either deferred until they're real, or simply not needed for a personal-scale system.

## Alternatives considered

- **Postgres for everything** (drafts, tool_calls, migration_log, pending_episodes, dedup_candidates). Originally justified by "we already have it on the VPS" via OpenClaw. Cut when that assumption went away — the design is now generic and can't lean on an unrelated stack being present.
- **SQLite as a single-file replacement for Postgres.** Embedded in the PWA process, no extra container. Same five tables, just in SQLite. Cut as still-overkill for the actual needs.
