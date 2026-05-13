-- Track which migrations have run. The runner in scripts/migrate.mjs uses this
-- to skip already-applied files. When we add node-pg-migrate (>5 migrations
-- in), it gets pointed at this same table.

CREATE TABLE IF NOT EXISTS brain.schema_migrations (
  filename        TEXT PRIMARY KEY,
  applied_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
