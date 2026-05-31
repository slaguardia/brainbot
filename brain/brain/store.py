"""The document substrate — ingest + the three reads, over asyncpg + pgvector.

This is the whole brain in one file (the plan's "~200-line" skeleton, Phase-1
shape):

- **ingest** — `upsert_source` is capture = human-edit = Notion re-sync, all one
  call. It upserts the source row, then WIPES that source's chunks and re-inserts
  fresh, so re-posting the same URL is idempotent and always current
  ("currency by construction"). Phase 1 chunking is deliberately trivial: the
  WHOLE page is ONE chunk (position 0, heading = the page title) — no section
  splitting yet.
- **recall(query, scope)** — targeted hybrid retrieval. A semantic select (cosine
  distance over the HNSW index) and a lexical select (`ts_rank` over the GIN
  `tsvector`), each prefix-scoped by `sources.path` when a scope is given, fused
  by Reciprocal Rank Fusion (c=60) — reproducing graphiti's
  COMBINED_HYBRID_SEARCH_RRF. Returns the top-k `Chunk`s.
- **profile(scope, budget)** — domain dump. Every chunk under the path prefix,
  ordered by `(path, position)`, re-assembled into structured markdown as one
  `Context`. In Phase 1 a single page always fits the budget; the over-budget
  degrade-to-recall path is stubbed and documented below.
- **map_(scope)** — domain discovery: the `(path, title)` source tree under the
  prefix, so a consumer that doesn't know its scope can find it.

`embed()` (Voyage) and `fetch_page()` (Notion) are synchronous; async callers
here wrap `embed` with `asyncio.to_thread`. The asyncpg pool is owned by db.py
and passed in.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

import asyncpg

from .embed import embed

# RRF constant — the rank-fusion damping (graphiti's COMBINED_HYBRID_SEARCH_RRF
# uses the canonical 60). Larger c flattens the contribution of top ranks.
_RRF_C = 60

# Per-arm candidate cap before fusion: pull ~50 from each of the semantic and
# lexical selects, fuse, then slice to k. Wide enough that fusion has signal,
# small enough to stay cheap.
_ARM_LIMIT = 50


@dataclass
class Chunk:
    """One retrieved section — self-contained; the consumer LLM reads meaning
    straight from `text`. JSON-serializable via `to_dict`."""

    heading: str
    text: str
    score: float
    path: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    """The reusable contract every consumer app codes against: assembled markdown
    `text`, `sources` provenance, and whether the slice was cut to fit budget.
    JSON-serializable via `to_dict`."""

    text: str
    sources: list
    truncated: bool

    def to_dict(self) -> dict:
        return asdict(self)


# ---- ingest: capture = edit = re-sync, all one call --------------------------

async def upsert_source(
    pool: asyncpg.Pool,
    *,
    kind: str,
    title: str,
    raw_text: str,
    path: str,
    source_id: str | None = None,
) -> str:
    """Create or replace a source, then re-derive its chunks (wipe-replace).

    New capture, a human edit in the PWA, and a Notion re-sync are the same call.
    The source row is upserted; then every chunk it owns is DELETEd and a single
    whole-page chunk (position 0, heading = title) is re-inserted with its
    embedding. Re-posting the same `source_id` is idempotent and always current.

    Returns the source id (string uuid).
    """
    # Embed first (outside the txn) so an embedder failure aborts before we touch
    # the store — never leave a source with stale or zero chunks. The whole page
    # is one chunk in Phase 1; the heading gives the embedding a little context.
    page_text = raw_text or ""
    [embedding] = await asyncio.to_thread(embed, [f"{title}\n{page_text}"])

    async with pool.acquire() as conn:
        async with conn.transaction():
            src_id = await conn.fetchval(
                """
                INSERT INTO sources (id, kind, title, raw_text, path)
                VALUES (COALESCE($1::uuid, gen_random_uuid()), $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE
                  SET kind=$2, title=$3, raw_text=$4, path=$5,
                      version=sources.version+1, updated_at=now()
                RETURNING id
                """,
                source_id,
                kind,
                title,
                page_text,
                path,
            )
            # Wipe-replace: drop this source's chunks, re-insert the fresh one.
            await conn.execute("DELETE FROM chunks WHERE source_id=$1", src_id)
            await conn.execute(
                """
                INSERT INTO chunks (source_id, heading, text, position, embedding)
                VALUES ($1, $2, $3, 0, $4)
                """,
                src_id,
                title,
                page_text,
                embedding,
            )
    return str(src_id)


# ---- recall (Mode 1): targeted hybrid retrieval, path-scoped -----------------

async def recall(
    pool: asyncpg.Pool,
    query: str,
    *,
    scope: str | None = None,
    k: int = 12,
) -> list[Chunk]:
    """'Look something up.' Top-k sections matching `query`, optionally within a
    path subtree. Runs a semantic select (cosine distance) and a lexical select
    (`ts_rank`), each capped at ~50 and prefix-scoped by `sources.path`, then
    fuses them with RRF and returns the top-k `Chunk`s."""
    [q_emb] = await asyncio.to_thread(embed, [query])
    scope_like = f"{scope}%" if scope else "%"

    async with pool.acquire() as conn:
        semantic = await conn.fetch(
            """
            SELECT c.id,
                   c.heading,
                   c.text,
                   s.path,
                   row_number() OVER (ORDER BY c.embedding <=> $1) AS rank
            FROM chunks c JOIN sources s ON s.id = c.source_id
            WHERE s.path LIKE $2
            ORDER BY c.embedding <=> $1
            LIMIT $3
            """,
            q_emb,
            scope_like,
            _ARM_LIMIT,
        )
        lexical = await conn.fetch(
            """
            SELECT c.id,
                   c.heading,
                   c.text,
                   s.path,
                   row_number() OVER (
                       ORDER BY ts_rank(c.fts, plainto_tsquery('english', $1)) DESC
                   ) AS rank
            FROM chunks c JOIN sources s ON s.id = c.source_id
            WHERE c.fts @@ plainto_tsquery('english', $1) AND s.path LIKE $2
            LIMIT $3
            """,
            query,
            scope_like,
            _ARM_LIMIT,
        )
    return _rrf(semantic, lexical)[:k]


def _rrf(*rankings: list, c: int = _RRF_C) -> list[Chunk]:
    """Reciprocal Rank Fusion — reproduces graphiti's COMBINED_HYBRID_SEARCH_RRF.

    Each record contributes 1/(c + rank) to its id's fused score; ids appearing in
    both arms accumulate from both. Returns `Chunk`s ordered by fused score desc.
    """
    score: dict = {}
    row: dict = {}
    for ranking in rankings:
        for r in ranking:
            rid = r["id"]
            score[rid] = score.get(rid, 0.0) + 1.0 / (c + r["rank"])
            row[rid] = r
    order = sorted(score, key=lambda rid: score[rid], reverse=True)
    return [
        Chunk(
            heading=row[rid]["heading"] or "",
            text=row[rid]["text"],
            score=score[rid],
            path=row[rid]["path"],
        )
        for rid in order
    ]


# ---- profile (Mode 2): domain dump — completeness over precision -------------

async def profile(
    pool: asyncpg.Pool,
    scope: str,
    *,
    budget: int = 20_000,
) -> Context:
    """'Give me everything about this domain,' assembled. Pulls every chunk under
    the `scope` path prefix ordered by `(path, position)` so the human's structure
    survives, then rebuilds it into structured markdown.

    Phase 1: a single page always fits, so the common path returns the assembled
    bundle whole with `truncated=False`. The over-budget degrade — fall back to
    `recall`-within-scope and flag `truncated=True` rather than silently cut — is
    documented here and left as a stub: `_token_estimate` only trips when a future
    multi-section corpus exceeds `budget`.
    """
    scope_like = f"{scope}%"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.path, s.id AS source_id, s.title, s.updated_at,
                   c.heading, c.text, c.position
            FROM chunks c JOIN sources s ON s.id = c.source_id
            WHERE s.path LIKE $1
            ORDER BY s.path, c.position
            """,
            scope_like,
        )

    bundle = _assemble(rows)
    provenance = _provenance(rows)

    if _token_estimate(bundle) <= budget:
        # Common, safe case: the slice fits — hand it over whole.
        return Context(text=bundle, sources=provenance, truncated=False)

    # Over budget: degrade to recall-within-scope rather than silently truncating,
    # and SAY it was cut. (Phase 1 never reaches here for a single page; this is
    # the documented degrade path for a future multi-section corpus.)
    focused = await recall(pool, scope, scope=scope, k=40)
    return Context(
        text=_assemble_chunks(focused),
        sources=provenance,
        truncated=True,
    )


def _assemble(rows: list) -> str:
    """Rebuild the subtree as structured markdown — '# path / ## title /
    ### heading / body' — grouped by source so the human's authored shape (and
    provenance) survives, not a flat soup."""
    lines: list[str] = []
    last_path: str | None = None
    last_source: str | None = None
    for r in rows:
        path = r["path"] or ""
        source_key = str(r["source_id"])
        if path != last_path:
            lines.append(f"# {path}")
            last_path = path
            last_source = None
        if source_key != last_source:
            title = r["title"] or ""
            if title and title != path.rsplit("/", 1)[-1]:
                lines.append(f"## {title}")
            last_source = source_key
        heading = r["heading"] or ""
        if heading:
            lines.append(f"### {heading}")
        body = (r["text"] or "").strip()
        if body:
            lines.append(body)
    return "\n\n".join(lines).strip()


def _assemble_chunks(chunks: list[Chunk]) -> str:
    """Assemble a degraded (recall-within-scope) bundle: heading + body per chunk.
    Used only on the over-budget path."""
    lines: list[str] = []
    for ch in chunks:
        if ch.heading:
            lines.append(f"### {ch.heading}")
        body = (ch.text or "").strip()
        if body:
            lines.append(body)
    return "\n\n".join(lines).strip()


def _provenance(rows: list) -> list:
    """List of (path, source_id, last_edited) per distinct source, for citation —
    'per your Target role doc.' Order follows the assembled rows."""
    seen: set = set()
    out: list = []
    for r in rows:
        key = str(r["source_id"])
        if key in seen:
            continue
        seen.add(key)
        updated = r["updated_at"]
        out.append(
            {
                "path": r["path"] or "",
                "source_id": key,
                "title": r["title"] or "",
                "last_edited": updated.isoformat() if updated is not None else None,
            }
        )
    return out


def _token_estimate(text: str) -> int:
    """Rough token count for the budget check — ~4 chars/token. A cheap proxy; the
    only consumer is profile()'s fits-the-budget gate, where exactness doesn't
    matter (a single page is far under budget; the degrade is a safety net)."""
    return len(text) // 4


# ---- map (discovery): the source tree ----------------------------------------

async def map_(pool: asyncpg.Pool, scope: str | None = None) -> list[dict]:
    """Domain discovery: the `(path, title)` source tree under the prefix (or all
    sources), ordered by path — so a consumer that doesn't know its scope can find
    it."""
    scope_like = f"{scope}%" if scope else "%"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT path, title
            FROM sources
            WHERE path LIKE $1
            ORDER BY path
            """,
            scope_like,
        )
    return [{"path": r["path"] or "", "title": r["title"] or ""} for r in rows]
