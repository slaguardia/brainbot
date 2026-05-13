-- Fire-and-forget queue for add_episode. The tool inserts a row here and
-- returns immediately; a background worker (not yet built) drains by calling
-- Graphiti's add_episode and marking rows done or failed.
--
-- Rationale: Graphiti extraction is 1-3s; blocking the chat response on it
-- would freeze the UI.

CREATE TABLE IF NOT EXISTS brain.pending_episodes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  name            TEXT NOT NULL,
  body            TEXT NOT NULL,
  source          TEXT NOT NULL DEFAULT 'chat',
  status          TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'done', 'failed')),
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TIMESTAMPTZ,
  error_message   TEXT,
  graphiti_episode_id TEXT
);

CREATE INDEX IF NOT EXISTS pending_episodes_status_idx
  ON brain.pending_episodes (status, created_at);
