-- Every tool invocation is logged here. Populated by lib/server/tools/instrument.ts.
-- Surfaced on /admin.

CREATE TABLE IF NOT EXISTS brain.tool_calls (
  id              BIGSERIAL PRIMARY KEY,
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  session_id      UUID,
  tool_name       TEXT NOT NULL,
  input_json      JSONB NOT NULL,
  output_json     JSONB,
  status          TEXT NOT NULL CHECK (status IN ('success', 'error', 'timeout')),
  latency_ms      INTEGER NOT NULL,
  model           TEXT,
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cost_usd        NUMERIC(12, 6),
  error_message   TEXT
);

CREATE INDEX IF NOT EXISTS tool_calls_occurred_idx
  ON brain.tool_calls (occurred_at DESC);

CREATE INDEX IF NOT EXISTS tool_calls_name_idx
  ON brain.tool_calls (tool_name, occurred_at DESC);

CREATE INDEX IF NOT EXISTS tool_calls_session_idx
  ON brain.tool_calls (session_id, occurred_at);
