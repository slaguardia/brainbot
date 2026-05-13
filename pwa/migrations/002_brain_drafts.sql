CREATE TABLE IF NOT EXISTS brain.drafts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  target_persona  TEXT,
  target_company  TEXT,
  channel         TEXT,
  subject         TEXT,
  body            TEXT NOT NULL,
  sent_at         TIMESTAMPTZ,
  episode_id      TEXT  -- set when promoted to a Graphiti episode
);

CREATE INDEX IF NOT EXISTS drafts_unsent_idx
  ON brain.drafts (created_at DESC)
  WHERE sent_at IS NULL;

CREATE INDEX IF NOT EXISTS drafts_company_idx
  ON brain.drafts (target_company)
  WHERE sent_at IS NULL;
