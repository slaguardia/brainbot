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
import logging
import math
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters

from .client import build_graphiti, cached_entity_types, cached_edge_types, cached_edge_type_map
from .config import Config
from .decompose import decompose

logger = logging.getLogger(__name__)


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
        self.edge_types = cached_edge_types()
        self.edge_type_map = cached_edge_type_map()
        self.anthropic = AsyncAnthropic(api_key=cfg.anthropic_api_key)

    async def init(self) -> None:
        await self.graphiti.build_indices_and_constraints()
        # Confirm the graph binding at boot. By construction database == group_id
        # (see build_graphiti), so a mismatch means a regression — log loudly
        # rather than silently serving the wrong graph. Resolves hypothesis #1
        # (wrong-graph-bound-at-construction) for good.
        bound = getattr(self.graphiti.driver, "_database", None)
        if bound != self.cfg.group_id:
            logger.error("brain graph binding MISMATCH: driver._database=%r group_id=%r", bound, self.cfg.group_id)
        logger.info("brain ready: group_id=%s graph=%s", self.cfg.group_id, bound)

    async def close(self) -> None:
        await self.graphiti.driver.close()

    async def _add(self, name: str, body: str, source_description: str, group_id: str) -> None:
        await self.graphiti.add_episode(
            name=name,
            episode_body=body,
            source=EpisodeType.text,
            source_description=source_description,
            reference_time=datetime.now(timezone.utc),
            group_id=group_id,
            entity_types=self.entity_types,
            edge_types=self.edge_types,
            edge_type_map=self.edge_type_map,
            custom_extraction_instructions=self.cfg.extraction_instructions,
        )

    async def capture(self, text: str, group_id: str | None = None) -> dict:
        """Rewrite + ingest as ONE episode. Returns a summary of what was written.

        The rewrite produces faithful, rule-preserving, named-subject prose; the
        override-tuned extractor pulls the facts from that single episode. No
        per-fact fan-out (that over-atomized, was slow, and shattered rules into
        instances — see ARCHITECTURE.md).

        group_id overrides the target graph (defaults to the configured one).
        Used for test isolation (e.g. a `smoketest` graph).
        """
        gid = group_id or self.cfg.group_id
        text = text.strip()
        if not text:
            raise ValueError("empty capture")

        if not self.cfg.decompose_enabled:
            await self._add(name=text[:55], body=text, source_description="capture:raw", group_id=gid)
            return {"mode": "raw", "episodes": 1, "topic": None}

        r = await decompose(self.anthropic, self.cfg.decompose_model, self.cfg.user_name, text)
        await self._add(name=r.topic, body=r.body, source_description="capture", group_id=gid)
        return {"mode": "rewrite", "episodes": 1, "topic": r.topic}

    async def recall(
        self, query: str, limit: int = 20, group_id: str | None = None, debug: bool = False
    ) -> dict:
        """Targeted retrieval for a question. Returns scored graph facts.

        Each fact is an entity-edge fact carrying an absolute on-target cosine
        score plus its `polarity`/`strength` (the two dimensions the extractor
        tags; null on facts it didn't tag). The graph is the source of truth —
        the consumer's LLM reasons over the facts.

        debug=False (default): facts only. debug=True re-includes the source
        episode bodies/refs under `episodes`, for human tracing/provenance only
        — not a knowledge surface (the graph is). A label can't stop an LLM
        reading inlined body text, so by default the bodies leave the payload.
        """
        gid = group_id or self.cfg.group_id
        cfg = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
        cfg.limit = limit
        res = await self.graphiti.search_(
            query=query,
            config=cfg,
            group_ids=[gid],
            search_filter=SearchFilters(),
        )

        facts: list[dict] = []
        edges = list(res.edges)
        if edges:
            # Absolute on-target score: search_ strips fact_embedding, so fetch
            # them for the candidate uuids and cosine against the query.
            query_emb = await self.graphiti.embedder.create(query)
            emb_map = await self._fact_embeddings([e.uuid for e in edges])
            scored = sorted(
                ((_cosine(query_emb, emb_map.get(e.uuid)), e) for e in edges),
                key=lambda t: t[0],
                reverse=True,
            )
            facts = [
                {
                    "fact": e.fact,
                    "name": e.name,
                    "score": round(s, 4),
                    "polarity": e.attributes.get("polarity"),
                    "strength": e.attributes.get("strength"),
                    "valid_at": e.valid_at.isoformat() if e.valid_at else None,
                    "invalid_at": e.invalid_at.isoformat() if e.invalid_at else None,
                }
                for s, e in scored
            ]

        out: dict = {"facts": facts}
        if debug:
            out["episodes"] = [{"name": ep.name, "body": ep.content} for ep in (res.episodes or [])]
        logger.debug("recall gid=%s q=%r -> %d facts (debug=%s)", gid, query, len(facts), debug)
        return out

    async def _fact_embeddings(self, uuids: list[str]) -> dict[str, list[float]]:
        if not uuids:
            return {}
        records, _, _ = await self.graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.uuid IN $uuids "
            "RETURN r.uuid AS uuid, r.fact_embedding AS emb",
            uuids=uuids,
        )
        return {r["uuid"]: r["emb"] for r in records if r.get("emb")}

    async def profile(self, group_id: str | None = None) -> dict:
        """Full-profile dump from the GRAPH: every CURRENT fact, flat.

        Returns all live `RELATES_TO` facts — `invalid_at`/`expired_at` IS NULL,
        i.e. not bi-temporally superseded — each carrying its `polarity` and
        `strength` (the two dimensions the extractor now tags). The graph is the
        source of truth; the consumer's LLM reasons over the facts. A flat list,
        no grouping, no synthesis (ARCHITECTURE.md principles #4, #6). Newest
        first. `polarity`/`strength` fall back to null on facts the extractor
        didn't tag.

        group_id overrides the target graph (defaults to the configured one).
        """
        gid = group_id or self.cfg.group_id
        records, _, _ = await self.graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() "
            "WHERE r.group_id = $gid AND r.invalid_at IS NULL AND r.expired_at IS NULL "
            "RETURN r.fact AS fact, r.name AS name, r.polarity AS polarity, "
            "r.strength AS strength, r.valid_at AS valid_at, r.created_at AS created_at "
            "ORDER BY r.created_at DESC",
            gid=gid,
        )
        facts = [
            {
                "fact": r.get("fact"),
                "polarity": r.get("polarity"),
                "strength": r.get("strength"),
                "valid_at": r.get("valid_at"),
                "name": r.get("name"),
            }
            for r in records
            if r.get("fact")
        ]
        if not facts:
            # The exact symptom of the stale-connection bug: a healthy graph with
            # data, but the long-lived connection returns nothing. Make it visible.
            logger.warning(
                "profile returned 0 facts for group_id=%s (graph=%s) — if data is expected, "
                "suspect a dead pooled connection",
                gid,
                getattr(self.graphiti.driver, "_database", None),
            )
        else:
            logger.debug("profile gid=%s -> %d facts", gid, len(facts))
        return {"facts": facts}


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
