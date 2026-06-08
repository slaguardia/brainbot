"""Brain service configuration — all from env, with sane defaults.

The brain is a pgvector document store: sources are split into section-chunks,
embedded with Voyage, stored in Postgres+pgvector. There is no graphiti, no
FalkorDB, and no write-time LLM. Config is just the four things the substrate
needs: the Postgres DSN, the Voyage key + model, and the Notion token for ingest.
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

    # Periodic Notion sync. Every `poll_interval_seconds` the brain re-ingests
    # pages whose Notion copy changed since it last captured them — so the brain
    # stays current even when no dashboard is open. Stale-only: it never adds
    # pages a human didn't pull. 0 disables the loop; default 1h.
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.environ.get("BRAIN_POLL_INTERVAL_SECONDS") or "3600")
    )

    def validate(self) -> None:
        missing = [n for n, v in (("VOYAGE_API_KEY", self.voyage_api_key),) if not v]
        if missing:
            raise RuntimeError(f"missing required env: {', '.join(missing)}")
