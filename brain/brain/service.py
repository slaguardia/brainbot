"""Brain operations: capture() and recall().

capture(text):
  decompose -> write the rewritten body as one episode + each atomic fact as
  its own episode, all with our custom_extraction_instructions and entity
  types. Calls graphiti-core directly, so the extraction tuning that the MCP
  server can't reach is applied here.

recall(query):
  hybrid edge search (RRF) for relevant facts. On a known-subject personal
  brain the graph is hub-shaped, so each fact already carries its domain
  context in the fact text — the consumer's LLM filters from there.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters

from .client import build_graphiti, cached_entity_types
from .config import Config
from .decompose import decompose


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Absolute cosine similarity in [0,1]-ish range. 0.0 if either is missing."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class Brain:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.graphiti: Graphiti = build_graphiti(cfg)
        self.entity_types = cached_entity_types()
        self.anthropic = AsyncAnthropic(api_key=cfg.anthropic_api_key)

    async def init(self) -> None:
        await self.graphiti.build_indices_and_constraints()

    async def close(self) -> None:
        await self.graphiti.driver.close()

    async def _add(self, name: str, body: str, source_description: str) -> None:
        await self.graphiti.add_episode(
            name=name,
            episode_body=body,
            source=EpisodeType.text,
            source_description=source_description,
            reference_time=datetime.now(timezone.utc),
            group_id=self.cfg.group_id,
            entity_types=self.entity_types,
            custom_extraction_instructions=self.cfg.extraction_instructions,
        )

    async def capture(self, text: str) -> dict:
        """Decompose + ingest. Returns a summary of what was written."""
        text = text.strip()
        if not text:
            raise ValueError("empty capture")

        if not self.cfg.decompose_enabled:
            await self._add(name=text[:55], body=text, source_description="capture:raw")
            return {"mode": "raw", "episodes": 1, "topic": None, "facts": 0}

        d = await decompose(self.anthropic, self.cfg.decompose_model, self.cfg.user_name, text)

        # Body episode first (preserves the coherent original meaning + is the
        # vector-search anchor), then each atomic fact.
        await self._add(name=d.topic, body=d.body, source_description="capture:body")
        for fact in d.facts:
            await self._add(name=fact[:55].rstrip(".") + "...", body=fact, source_description="capture:fact")

        return {"mode": "decomposed", "episodes": 1 + len(d.facts), "topic": d.topic, "facts": len(d.facts)}

    async def recall(self, query: str, limit: int = 20) -> list[dict]:
        """Targeted retrieval for a question. Returns scored fact records.

        Hybrid search (RRF: BM25 + vector) selects candidates for breadth, then
        each fact gets an absolute "on-target" cosine score = cosine(query
        embedding, fact embedding). The brain reports the score; it does NOT
        threshold — the app decides what's strong enough (see ARCHITECTURE.md).
        All-low scores = the brain doesn't really know this.
        """
        cfg = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        cfg.limit = limit
        res = await self.graphiti.search_(
            query=query,
            config=cfg,
            group_ids=[self.cfg.group_id],
            search_filter=SearchFilters(),
        )
        edges = list(res.edges)
        if not edges:
            return []

        # Absolute on-target score. search_ strips fact_embedding from results,
        # so fetch them for the candidate uuids, then cosine against the query.
        query_emb = await self.graphiti.embedder.create(query)
        emb_map = await self._fact_embeddings([e.uuid for e in edges])

        scored: list[tuple[float, object]] = []
        for e in edges:
            scored.append((_cosine(query_emb, emb_map.get(e.uuid)), e))
        scored.sort(key=lambda t: t[0], reverse=True)

        return [
            {
                "fact": e.fact,
                "name": e.name,
                "score": round(score, 4),
                "valid_at": e.valid_at.isoformat() if e.valid_at else None,
                "invalid_at": e.invalid_at.isoformat() if e.invalid_at else None,
            }
            for score, e in scored
        ]

    async def _fact_embeddings(self, uuids: list[str]) -> dict[str, list[float]]:
        if not uuids:
            return {}
        records, _, _ = await self.graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.uuid IN $uuids "
            "RETURN r.uuid AS uuid, r.fact_embedding AS emb",
            uuids=uuids,
        )
        return {r["uuid"]: r["emb"] for r in records if r.get("emb")}

    async def profile(self) -> list[dict]:
        """Full-profile dump: every CURRENT fact about the user, unscored.

        The blind-spot fix at current scale — the consumer reasons over the
        whole profile, so nothing relevant can be missed (see ARCHITECTURE.md).
        `expired_at IS NULL` excludes bi-temporally superseded facts; only
        currently-true facts are returned. Newest first.
        """
        records, _, _ = await self.graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() "
            "WHERE r.group_id = $gid AND r.expired_at IS NULL "
            "RETURN r.fact AS fact, r.name AS name, r.valid_at AS valid_at, "
            "r.invalid_at AS invalid_at, r.created_at AS created_at "
            "ORDER BY r.created_at DESC",
            gid=self.cfg.group_id,
        )
        return [
            {
                "fact": r.get("fact"),
                "name": r.get("name"),
                "valid_at": r.get("valid_at"),
                "invalid_at": r.get("invalid_at"),
            }
            for r in records
            if r.get("fact")
        ]


async def _smoke() -> None:
    """Manual smoke: python -m brain.service"""
    cfg = Config()
    brain = Brain(cfg)
    await brain.init()
    try:
        for q in [
            "What does the user want in their next job?",
            "What are the user's fitness and training priorities?",
        ]:
            print("=" * 70)
            print("Q:", q)
            for f in await brain.recall(q, limit=8):
                print(f"  • [{f['name']}] {f['fact']}")
    finally:
        await brain.close()


if __name__ == "__main__":
    asyncio.run(_smoke())
