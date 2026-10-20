"""Embedding — the one storage-agnostic piece carried over from the old stack.

Calls a local Ollama's `/api/embed`: `embed(texts) -> list[list[float]]`, one
EMBED_DIM-vector per input, batched in one request. Stdlib HTTP and synchronous,
so this is a plain function — callers in async code wrap it with
`asyncio.to_thread(embed, ...)`.

Errors surface: an unreachable Ollama or a bad response raises rather than
returning empty vectors, so a misconfig fails loud at ingest time instead of
poisoning the store with bad embeddings. recall() catches it and degrades to
lexical-only.
"""

from __future__ import annotations

import json
import urllib.request

from .config import EMBED_DIM, Config

# Retrieval models embed queries and documents asymmetrically via text prefixes
# (each model card's documented convention). Keyed by model name without tag.
_PREFIXES: dict[str, tuple[str, str]] = {  # model -> (query, document)
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "embeddinggemma": ("task: search result | query: ", "title: none | text: "),
    "mxbai-embed-large": ("Represent this sentence for searching relevant passages: ", ""),
    "qwen3-embedding": (
        "Instruct: Given a search query, retrieve relevant passages that answer the query\nQuery: ",
        "",
    ),
}

# A query sits on recall's hot path — fail fast so the lexical fallback kicks in;
# a document batch (ingest, re-embed) is CPU-bound and can legitimately take long.
_TIMEOUT_S = {"query": 15, "document": 600}


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a batch of texts with Ollama (model = BRAIN_EMBED_MODEL).

    Returns one float-vector per input text, in input order. The vectors are
    EMBED_DIM-dimensional to match the chunks.embedding column. Synchronous —
    wrap with asyncio.to_thread in async callers.

    input_type: "document" for stored content (ingest), "query" for recall
    queries — the model's prefix convention embeds the two sides asymmetrically.
    """
    if not texts:
        return []
    cfg = Config()
    q_prefix, d_prefix = _PREFIXES.get(cfg.embed_model.split(":")[0], ("", ""))
    prefix = q_prefix if input_type == "query" else d_prefix
    req = urllib.request.Request(
        f"{cfg.embed_url}/api/embed",
        data=json.dumps(
            {"model": cfg.embed_model, "input": [prefix + t for t in texts]}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S[input_type]) as resp:
        embeddings = json.load(resp)["embeddings"]
    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"ollama returned {len(embeddings)} embeddings for {len(texts)} inputs"
        )
    for vec in embeddings:
        if len(vec) != EMBED_DIM:
            raise RuntimeError(
                f"ollama returned dim {len(vec)}, expected {EMBED_DIM} "
                f"(model={cfg.embed_model}) — set BRAIN_EMBED_DIM to match"
            )
    return embeddings
