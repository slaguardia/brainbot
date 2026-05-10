CREATE SCHEMA IF NOT EXISTS brain;

CREATE TABLE IF NOT EXISTS brain.migration_log (
  notion_page_id      TEXT        NOT NULL PRIMARY KEY,
  target_id           TEXT        NOT NULL,
  notion_last_edited  TIMESTAMPTZ NOT NULL,
  graphiti_episode_id TEXT        NOT NULL,
  migrated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS migration_log_target_id_idx
    ON brain.migration_log (target_id);
