"""The document substrate — ingest + the three reads, over asyncpg + pgvector.

This is the whole brain in one file (the plan's "~200-line" skeleton):

- **ingest** — `upsert_source` is capture = human-edit = Notion re-sync, all one
  call. It upserts the source row, then WIPES that source's chunks and re-inserts
  fresh, so re-posting the same URL is idempotent and always current
  ("currency by construction"). The page is split into SECTIONS by its own
  heading structure (`_split_sections`) — one chunk per section, each embedded on
  its own so recall can discriminate within a page (a query about one section's
  topic ranks it above the others, instead of the whole page scoring flat).
- **recall(query, scope)** — targeted hybrid retrieval. A semantic select (cosine
  distance over the HNSW index) and a lexical select (`ts_rank` over the GIN
  `tsvector`), each prefix-scoped by `sources.path` when a scope is given, fused
  by Reciprocal Rank Fusion (c=60) — reproducing graphiti's
  COMBINED_HYBRID_SEARCH_RRF. Returns the top-k `Chunk`s — or, with
  `complete=True`, everything the brain itself judges relevant (it derives the
  cutoff from its own semantic similarities; k stays a safety cap).
- **profile(scope, budget)** — domain dump. Every chunk under the path prefix,
  ordered by `(path, position)`, re-assembled into structured markdown as one
  `Context`. A small corpus fits the budget; the over-budget degrade-to-recall
  path is documented below.
- **map_(scope)** — domain discovery: the `(path, title)` source tree under the
  prefix, so a consumer that doesn't know its scope can find it.

`embed()` (Voyage) and `fetch_page()` (Notion) are synchronous; async callers
here wrap `embed` with `asyncio.to_thread`. The asyncpg pool is owned by db.py
and passed in.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime

import asyncpg

from .embed import embed

logger = logging.getLogger(__name__)

# RRF constant — the rank-fusion damping (graphiti's COMBINED_HYBRID_SEARCH_RRF
# uses the canonical 60). Larger c flattens the contribution of top ranks.
_RRF_C = 60

# Per-arm candidate cap before fusion: pull ~50 from each of the semantic and
# lexical selects, fuse, then slice to k. Wide enough that fusion has signal,
# small enough to stay cheap.
_ARM_LIMIT = 50

# Complete-mode cutoff: keep semantic candidates whose cosine similarity is
# within this fraction of the best hit's. Brain-INTERNAL — consumers say
# `complete=true` and never see a score scale; this can be tuned (or replaced
# with something smarter) without any contract change.
_COMPLETE_SIM_FLOOR = 0.85

# Embed-input char budget. voyage-3-lite caps a single input near ~32K tokens; at
# a conservative ~4 chars/token that's ~110K chars (≈28K tokens, with headroom).
# A very large section is truncated to this before embedding so /ingest never
# 500s on Voyage's single-input cap.
_EMBED_CHAR_BUDGET = 110_000

# A markdown heading line: 1-6 '#' then whitespace then the heading text. Notion's
# flattener (notion.py) emits h1-h3, but match h1-h6 so any markdown source splits.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    """One retrieved section — self-contained; the consumer LLM reads meaning
    straight from `text`. The public recall contract is heading/text/score/path
    (see `to_dict`). `source_id` is internal provenance (which source the chunk came
    from), used by profile()'s degrade path; it is deliberately NOT in `to_dict`."""

    heading: str
    text: str
    score: float
    path: str
    source_id: str = ""

    def to_dict(self) -> dict:
        # The 4-key recall contract — source_id stays internal.
        return {
            "heading": self.heading,
            "text": self.text,
            "score": self.score,
            "path": self.path,
        }


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

def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (e.g. Notion's last_edited_time) to a datetime
    for the timestamptz column. Tolerates a trailing 'Z'; returns None on
    missing/unparseable input rather than failing the ingest."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _split_sections(title: str, text: str) -> list[tuple[str, str]]:
    """Split a page's markdown into (heading, body) sections by its OWN heading
    structure — one section per heading line, plus a leading section for any
    preamble before the first heading (whose heading is the page title).

    This is the foundation of recall precision: each section is embedded on its
    own, so a query about one topic ranks that section above the others on the
    same page instead of the whole page scoring flat. A page with no headings
    stays a single (title, body) section — same shape as before.

    Heading lines are consumed into the section's `heading`, never its `body`;
    profile re-emits '### heading' when it reassembles, so the human's structure
    round-trips. A real heading section is kept even with an empty body (the
    heading is signal); the synthetic preamble section is kept only when it has
    body, so a page that leads with a heading doesn't gain an empty title chunk.
    The guard at the end guarantees at least one section for an empty page.
    """
    sections: list[tuple[str, str]] = []
    heading = title.strip()
    body_lines: list[str] = []
    is_preamble = True  # the leading section's heading is the title, not a real header

    def flush() -> None:
        body = "\n".join(body_lines).strip()
        if body or (heading and not is_preamble):
            sections.append((heading, body))

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            heading = m.group(2).strip()
            body_lines = []
            is_preamble = False
        else:
            body_lines.append(line)
    flush()

    if not sections:
        sections.append((title.strip(), ""))
    return sections


def _embed_input(heading: str, body: str) -> str:
    """The text embedded for a section: its heading + body, truncated to the
    embedder's single-input budget. Deliberately section-LOCAL (the page title is
    NOT injected) so sections of the same page stay distinguishable in vector
    space — injecting a shared title would pull them back together and defeat the
    point of section chunking."""
    text = f"{heading}\n{body}".strip() if heading else body.strip()
    if len(text) > _EMBED_CHAR_BUDGET:
        logger.warning(
            "section embed input %d chars exceeds budget %d; truncating (heading=%r)",
            len(text),
            _EMBED_CHAR_BUDGET,
            heading,
        )
        text = text[:_EMBED_CHAR_BUDGET]
    return text


async def upsert_source(
    pool: asyncpg.Pool,
    *,
    kind: str,
    title: str,
    raw_text: str,
    path: str,
    source_id: str | None = None,
    last_edited: str | None = None,
) -> tuple[str, int]:
    """Create or replace a source, then re-derive its chunks (wipe-replace).

    New capture, a human edit in the PWA, and a Notion re-sync are the same call.
    The source row is upserted; then every chunk it owns is DELETEd and one chunk
    per SECTION (`_split_sections`) is re-inserted, each with its own embedding.
    Re-posting the same `source_id` is idempotent and always current.

    Returns (source id, chunk count).
    """
    # Postgres text columns can't hold a NUL byte (U+0000); Notion plain_text can
    # rarely carry one. Strip it everywhere so the page still ingests instead of the
    # INSERT raising and turning caller-fixable content into a 500.
    title = (title or "").replace("\x00", "")
    path = (path or "").replace("\x00", "")
    page_text = (raw_text or "").replace("\x00", "")
    # The source's real edit time (e.g. Notion's last_edited_time), parsed to a
    # datetime for the timestamptz column. None when the origin doesn't supply it.
    last_edited_dt = _parse_iso(last_edited)

    # Split into sections, then embed all of them in ONE batched Voyage call.
    # Embed first (outside the txn) so an embedder failure aborts before we touch
    # the store — never leave a source with stale or zero chunks.
    sections = _split_sections(title, page_text)
    embed_inputs = [_embed_input(h, b) for h, b in sections]
    embeddings = await asyncio.to_thread(embed, embed_inputs)

    async with pool.acquire() as conn:
        async with conn.transaction():
            src_id = await conn.fetchval(
                """
                INSERT INTO sources (id, kind, title, raw_text, path, source_last_edited)
                VALUES (COALESCE($1::uuid, gen_random_uuid()), $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE
                  SET kind=$2, title=$3, raw_text=$4, path=$5, source_last_edited=$6,
                      version=sources.version+1, updated_at=now()
                RETURNING id
                """,
                source_id,
                kind,
                title,
                page_text,
                path,
                last_edited_dt,
            )
            # Wipe-replace: drop this source's chunks, re-insert one per section
            # (position = document order, so profile reassembles in the human's order).
            await conn.execute("DELETE FROM chunks WHERE source_id=$1", src_id)
            await conn.executemany(
                """
                INSERT INTO chunks (source_id, heading, text, position, embedding)
                VALUES ($1, $2, $3, $4, $5)
                """,
                [
                    (src_id, heading, body, position, embedding)
                    for position, ((heading, body), embedding) in enumerate(
                        zip(sections, embeddings)
                    )
                ],
            )
    return str(src_id), len(sections)


# ---- recall (Mode 1): targeted hybrid retrieval, path-scoped -----------------

async def recall(
    pool: asyncpg.Pool,
    query: str,
    *,
    scope: str | None = None,
    k: int = 12,
    complete: bool = False,
) -> list[Chunk]:
    """'Look something up.' Sections matching `query`, optionally within a path
    subtree. Runs a semantic select (cosine distance) and a lexical select
    (`ts_rank`), each capped at ~50 and scoped to `sources.path` (the exact node
    or its proper subtree), then fuses them with RRF.

    By default returns the top-k. With `complete=True` — the 'return everything
    relevant' mode for completeness-sensitive consumers — the BRAIN decides where
    relevance ends: it trims the semantic candidates at its own similarity cutoff
    (`_trim_to_relevant`) before fusion, with `k` kept as a safety cap. The
    consumer never supplies or sees a score scale; how the cutoff is chosen is
    the librarian's business and can change without any contract change."""
    # Empty/whitespace scope means UNSCOPED, not "match the root prefix".
    if scope is not None:
        scope = scope.strip() or None
    k = max(1, min(k, 100))  # clamp in the core so MCP/SDK callers are guarded, not just the HTTP route

    [q_emb] = await asyncio.to_thread(embed, [query], "query")

    # Scope = the exact node OR its proper subtree (never a bare prefix, which
    # over-matches sibling paths). The subtree arm uses a wildcard-free prefix
    # compare (`left(...) = scope || '/'`) so `_`/`%`/spaces in a Notion path
    # are literal, not LIKE metacharacters. $2 carries the scope when present;
    # when scope is None there's no path filter, so $2 is the arm limit instead.
    sem_scope = "" if scope is None else "WHERE (s.path = $2 OR left(s.path, length($2) + 1) = $2 || '/')"
    lex_scope = "" if scope is None else "AND (s.path = $2 OR left(s.path, length($2) + 1) = $2 || '/')"
    limit_ph = "$2" if scope is None else "$3"
    sem_args = [q_emb, _ARM_LIMIT] if scope is None else [q_emb, scope, _ARM_LIMIT]
    lex_args = [query, _ARM_LIMIT] if scope is None else [query, scope, _ARM_LIMIT]

    async with pool.acquire() as conn:
        # Both arms share ONE snapshot so a wipe-replace committing between them
        # can't make the semantic arm see the old chunk id and the lexical arm the
        # new one — which would fuse the same page in twice. Read-only: no locks.
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            semantic = await conn.fetch(
                f"""
                SELECT c.id,
                       c.heading,
                       c.text,
                       s.path,
                       s.id AS source_id,
                       row_number() OVER (ORDER BY c.embedding <=> $1) AS rank,
                       1 - (c.embedding <=> $1) AS sim
                FROM chunks c JOIN sources s ON s.id = c.source_id
                {sem_scope}
                ORDER BY c.embedding <=> $1
                LIMIT {limit_ph}
                """,
                *sem_args,
            )
            lexical = await conn.fetch(
                f"""
                SELECT c.id,
                       c.heading,
                       c.text,
                       s.path,
                       s.id AS source_id,
                       row_number() OVER (
                           ORDER BY ts_rank(c.fts, plainto_tsquery('english', $1)) DESC
                       ) AS rank
                FROM chunks c JOIN sources s ON s.id = c.source_id
                WHERE c.fts @@ plainto_tsquery('english', $1)
                  {lex_scope}
                ORDER BY ts_rank(c.fts, plainto_tsquery('english', $1)) DESC
                LIMIT {limit_ph}
                """,
                *lex_args,
            )
    if complete:
        # Trim the semantic arm at the brain's own relevance cutoff BEFORE fusion;
        # lexical hits survive untrimmed (plainto_tsquery ANDs every lexeme, so a
        # lexical match is strong evidence of relevance on its own).
        semantic = _trim_to_relevant(semantic)
    return _rrf(semantic, lexical)[:k]


def _trim_to_relevant(semantic: list) -> list:
    """Complete-mode cutoff — the brain's own judgment of where relevance ends.

    Keeps the semantic candidates whose cosine similarity (`sim`) is within
    `_COMPLETE_SIM_FLOOR` of the best hit's. The cutoff works on similarity
    MAGNITUDES, not the RRF fused score: RRF is rank-only (1/(c+rank) sums), so
    it carries no signal about how close anything actually is and can't be
    thresholded meaningfully. A relative floor degrades gracefully: a flat,
    undifferentiated corpus keeps everything (k still caps) instead of cutting
    on noise."""
    if len(semantic) < 2:
        return semantic
    top = semantic[0]["sim"]
    if top <= 0:
        return semantic
    floor = top * _COMPLETE_SIM_FLOOR
    return [r for r in semantic if r["sim"] >= floor]


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
            source_id=str(row[rid]["source_id"]),
        )
        for rid in order
    ]


# ---- profile (Mode 2): domain dump — completeness over precision -------------

async def profile(
    pool: asyncpg.Pool,
    scope: str,
    *,
    budget: int = 20_000,
    focus: str | None = None,
) -> Context:
    """'Give me everything about this domain,' assembled. Pulls every chunk under
    the `scope` path prefix ordered by `(path, position)` so the human's structure
    survives, then rebuilds it into structured markdown.

    `focus` is an optional query used only on the over-budget degrade path to pick
    which sections survive (falls back to `scope` when not given).

    Phase 1: a single page always fits, so the common path returns the assembled
    bundle whole with `truncated=False`. The over-budget degrade — fall back to
    `recall`-within-scope and flag `truncated=True` rather than silently cut — is
    documented here and left as a stub: `_token_estimate` only trips when a future
    multi-section corpus exceeds `budget`.
    """
    # profile requires a non-empty scope and fails closed on empty/whitespace. The
    # HTTP route rejects empty, but a bare ' ' bypasses that guard and MCP/SDK
    # callers have no route guard at all — without this, scope='' would match only
    # empty-path sources and the over-budget degrade would recall the whole brain.
    scope = (scope or "").strip()
    if not scope:
        raise ValueError("profile requires a non-empty scope")
    # A non-positive budget (garbage/negative) means "use the default", not "force
    # the degrade path" — clamp in the core so MCP/SDK callers are guarded too.
    if budget <= 0:
        budget = 20_000

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.path, s.id AS source_id, s.title, s.source_last_edited,
                   c.heading, c.text, c.position
            FROM chunks c JOIN sources s ON s.id = c.source_id
            WHERE (s.path = $1 OR left(s.path, length($1) + 1) = $1 || '/')
            ORDER BY s.path, c.position
            """,
            scope,
        )

    bundle = _assemble(rows)

    if _token_estimate(bundle) <= budget:
        # Common, safe case: the slice fits — hand it over whole.
        return Context(text=bundle, sources=_provenance(rows), truncated=False)

    # Over budget: degrade to recall-within-scope rather than silently truncating,
    # and SAY it was cut. (Phase 1 never reaches here for a single page; this is
    # the documented degrade path for a future multi-section corpus.)
    focused = await recall(pool, focus or scope, scope=scope, k=40)
    # Provenance must match the text actually returned, in the same order, AND keep
    # the contract's 4-key shape. Key by SOURCE ID (not path — distinct sources can
    # share a path subtree, which would over-include), recovering full provenance
    # from the rows already fetched, in the focused chunks' relevance order.
    by_id = {str(r["source_id"]): r for r in rows}
    degraded_rows = [
        by_id[sid]
        for sid in dict.fromkeys(ch.source_id for ch in focused)
        if sid in by_id
    ]
    return Context(
        text=_assemble_chunks(focused),
        sources=_provenance(degraded_rows),
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
            if path:  # skip a bare '# ' header for an empty-path source
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
    """List of (path, source_id, title, last_edited) per distinct source, for
    citation — 'per your Target role doc.' `last_edited` is the source's REAL edit
    time at its origin (Notion's last_edited_time), not our ingest/sync time; it is
    None when the origin didn't supply one. Order follows the assembled rows."""
    seen: set = set()
    out: list = []
    for r in rows:
        key = str(r["source_id"])
        if key in seen:
            continue
        seen.add(key)
        edited = r["source_last_edited"]
        out.append(
            {
                "path": r["path"] or "",
                "source_id": key,
                "title": r["title"] or "",
                "last_edited": edited.isoformat() if edited is not None else None,
            }
        )
    return out


def _token_estimate(text: str) -> int:
    """Rough token count for the budget check — ~4 chars/token. A cheap proxy; the
    only consumer is profile()'s fits-the-budget gate, where exactness doesn't
    matter (a single page is far under budget; the degrade is a safety net)."""
    return len(text) // 4


async def source_ids(pool: asyncpg.Pool) -> set[str]:
    """The ids of every ingested source — lets /notion/pages flag which of the
    integration-visible pages are already in the brain (Notion page uuid == our
    source id)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM sources")
    return {str(r["id"]) for r in rows}


# ---- map (discovery): the source tree ----------------------------------------

async def map_(pool: asyncpg.Pool, scope: str | None = None) -> list[dict]:
    """Domain discovery: the `(path, title)` source tree under the prefix (or all
    sources), ordered by path — so a consumer that doesn't know its scope can find
    it."""
    # Empty/whitespace scope means UNSCOPED, not "match the root prefix".
    if scope is not None:
        scope = scope.strip() or None

    # Scope = the exact node OR its proper subtree; no path filter when scope is
    # None. The subtree arm is wildcard-free (`left(...) = scope || '/'`) so
    # `_`/`%`/spaces in a path are literal, not LIKE metacharacters.
    scope_clause = "" if scope is None else "WHERE (path = $1 OR left(path, length($1) + 1) = $1 || '/')"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT path, title
            FROM sources
            {scope_clause}
            ORDER BY path
            """,
            *([scope] if scope is not None else []),
        )
    return [{"path": r["path"] or "", "title": r["title"] or ""} for r in rows]
