"""Embedding — the one storage-agnostic piece carried over from the old stack.

Wraps the Voyage SDK: `embed(texts) -> list[list[float]]`, one EMBED_DIM-vector
per input, batched in one API call. The Voyage SDK is synchronous, so this is a
plain function — callers in async code wrap it with `asyncio.to_thread(embed, ...)`.

Errors surface: a missing key or an SDK/API failure raises rather than returning
empty vectors, so a misconfig fails loud at ingest time instead of poisoning the
store with bad embeddings.
"""

from __future__ import annotations

import voyageai

from .config import EMBED_DIM, Config

_client: voyageai.Client | None = None


def _get_client(cfg: Config) -> voyageai.Client:
    """Process-wide Voyage client, built lazily. Missing key fails loud."""
    global _client
    if not cfg.voyage_api_key:
        raise RuntimeError("missing required env: VOYAGE_API_KEY")
    if _client is None:
        _client = voyageai.Client(api_key=cfg.voyage_api_key)
    return _client


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a batch of texts with Voyage (model = BRAIN_EMBED_MODEL).

    Returns one float-vector per input text, in input order. The vectors are
    EMBED_DIM-dimensional (voyage-3-lite = 512) to match the chunks.embedding
    column. Synchronous — wrap with asyncio.to_thread in async callers.

    input_type: "document" for stored content (ingest), "query" for recall
    queries — Voyage embeds the two sides asymmetrically for better retrieval.
    """
    if not texts:
        return []
    cfg = Config()
    client = _get_client(cfg)
    # One batched call (Voyage accepts a list) keeps ingest a single round-trip.
    result = client.embed(texts, model=cfg.embed_model, input_type=input_type)
    embeddings = result.embeddings
    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"voyage returned {len(embeddings)} embeddings for {len(texts)} inputs"
        )
    for vec in embeddings:
        if len(vec) != EMBED_DIM:
            raise RuntimeError(
                f"voyage returned dim {len(vec)}, expected {EMBED_DIM} "
                f"(model={cfg.embed_model}) — column/embedder dim mismatch"
            )
    return embeddings
