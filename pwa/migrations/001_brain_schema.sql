-- Brainbot uses a dedicated `brain` schema inside the existing `personal`
-- database. Graphiti's own data lives in FalkorDB, not Postgres. Postgres
-- stores app state: drafts, tool-call logs, pending episodes, conversations.

CREATE SCHEMA IF NOT EXISTS brain;
