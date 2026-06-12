"""Brain service configuration — all from env, with sane defaults.

The brain is a pgvector document store: sources are split into section-chunks,
embedded with Voyage, stored in Postgres+pgvector. There is no graphiti and no
FalkorDB. There is no write-time LLM *by default* — the optional note-legibility
layer (docs/note-legibility.md) adds one at the edge of ingest, gated by a runtime
DB setting; its secret (`anthropic_api_key`) is read here, but the on/off switch
lives in the `settings` table, not env. Config is the substrate's deploy secrets +
defaults: the Postgres DSN, the Voyage key + model, the Notion token, the poll
interval, and the (optional) Anthropic key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# Embedding dimension — voyage-3-lite is 512-dim, so the chunks.embedding column
# is vector(512). Single shared constant: the DDL (next task) references this so
# the column dim and the embedder can never silently drift apart.
EMBED_DIM = 512


@dataclass(frozen=True)
class Config:
    # Postgres (pgvector). One DSN; one pool is built from it in db.py.
    pg_dsn: str = field(
        default_factory=lambda: os.environ.get(
            "PG_DSN", "postgresql://brain:brain@postgres:5432/brain"
        )
    )

    # Embedder (Voyage). voyage-3-lite -> EMBED_DIM dims.
    voyage_api_key: str = field(default_factory=lambda: os.environ.get("VOYAGE_API_KEY", ""))
    embed_model: str = field(default_factory=lambda: os.environ.get("BRAIN_EMBED_MODEL", "voyage-3-lite"))

    # Notion ingest.
    notion_token: str = field(default_factory=lambda: os.environ.get("NOTION_TOKEN", ""))

    # Note-legibility LLM (opt-in; see docs/note-legibility.md). A DEPLOYMENT SECRET,
    # read once here like VOYAGE_API_KEY — never stored in the DB. The on/off switch
    # is NOT here: it's the `legibility.*` runtime settings (settings table). Boot
    # stays key-agnostic — validate() does NOT require this, because whether the
    # feature is on is a DB value with no pool at boot. Enforcement is deferred to
    # settings._effective_legibility(), which degrades 'enabled but no key' to
    # pass-through. Empty string when unset.
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )

    # Periodic Notion sync. Every `poll_interval_seconds` the brain re-ingests
    # pages whose Notion copy changed since it last captured them — so the brain
    # stays current even when no dashboard is open. Stale-only: it never adds
    # pages a human didn't pull. 0 disables the loop; default 5m. A value set from
    # the PWA's #integrations page overrides this (see api._effective_poll_interval).
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.environ.get("BRAIN_POLL_INTERVAL_SECONDS") or "300")
    )

    def validate(self) -> None:
        missing = [n for n, v in (("VOYAGE_API_KEY", self.voyage_api_key),) if not v]
        if missing:
            raise RuntimeError(f"missing required env: {', '.join(missing)}")
