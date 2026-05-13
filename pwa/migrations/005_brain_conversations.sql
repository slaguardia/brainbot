-- Cross-device chat history (D4 — Postgres, not IndexedDB).
-- A conversation is a thread; messages belong to it.

CREATE TABLE IF NOT EXISTS brain.conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  title           TEXT,
  -- Soft-delete so old conversations don't litter the list but can be restored.
  archived_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS conversations_recent_idx
  ON brain.conversations (updated_at DESC)
  WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS brain.messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES brain.conversations (id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  -- Content is JSON: a plain string OR an array of content blocks (text + tool_use).
  content_json    JSONB NOT NULL,
  -- For instrumenting cost back to a specific user turn.
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  model           TEXT
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx
  ON brain.messages (conversation_id, created_at);
