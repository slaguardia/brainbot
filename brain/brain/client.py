"""Construct graphiti-core directly — no MCP server.

This is the architectural keystone: the brain owns its Graphiti instance
and gets full access to add_episode params (custom_extraction_instructions,
entity_types, edge_types) and the search_() recipe system — all of which
the MCP server hides.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from falkordb.asyncio import FalkorDB
from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.voyage import VoyageAIEmbedder, VoyageAIEmbedderConfig

from .config import Config, DEFAULT_ENTITY_TYPES


# Single generic typed edge. Deliberately NOT named per domain (no Targets /
# Avoids / Seeks) — the relationship verb lives in the edge's `fact` string;
# this just adds the two domain-agnostic dimensions the body-dump was covering
# for. polarity + strength apply to any life area (health, money, work,
# relationships), so there's no schema lock-in. graphiti extracts and persists
# these attributes onto the edge (its extract_attributes pass).
#
# The Field descriptions and Literal types below are not cosmetic: graphiti
# sends this model's JSON schema (docstring + field descriptions + allowed
# values) to the extractor LLM. Plain `#` comments are invisible to it, so the
# vocabulary has to live in the schema or the attributes come back null.
class Asserts(BaseModel):
    """A stance the owner holds toward a topic/thing — any thing the brain
    should remember they seek, value, accept, avoid, reject, or refuse.
    Apply whenever the fact expresses how the owner relates to the target."""

    polarity: Literal["positive", "negative"] = Field(
        description="positive if the owner seeks/values/accepts the target; "
        "negative if the owner avoids/rejects/refuses it."
    )
    strength: Literal["hard", "soft"] = Field(
        description="how strongly the owner holds the stance: hard if held as a "
        "requirement or dealbreaker; soft if a mild preference."
    )


# Allow the generic Asserts edge between any two entities. Mapped broadly so it
# applies across domains rather than locking it to specific entity pairs.
DEFAULT_EDGE_TYPES: dict[str, type[BaseModel]] = {"Asserts": Asserts}
DEFAULT_EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {("Entity", "Entity"): ["Asserts"]}


def build_entity_types(types: dict[str, str] | None = None) -> dict[str, type[BaseModel]]:
    """Turn {name: description} into the {name: PydanticModel} dict graphiti
    expects. Each model is empty (docstring-only) — no required attributes,
    so no schema lock-in; the description steers classification."""
    src = types or DEFAULT_ENTITY_TYPES
    out: dict[str, type[BaseModel]] = {}
    for name, description in src.items():
        # 'name' is a protected Pydantic attr — only the docstring carries info.
        out[name] = type(name, (BaseModel,), {"__doc__": description})
    return out


def build_graphiti(cfg: Config) -> Graphiti:
    cfg.validate()
    # Build the FalkorDB (redis.asyncio) client ourselves so we can harden the
    # connection — FalkorDriver doesn't forward these kwargs — then inject it.
    # This is the fix for the long-lived-singleton "recall silently returns 0"
    # bug: a dead pooled connection used to persist until a manual process
    # restart. health_check_interval pings idle connections before reuse so a
    # dead one is recycled (our actual failure mode: an idle socket reaped while
    # the FalkorDB server stayed healthy); keepalive + timeouts bound a hung
    # socket. Recovery from a connection that fully dies is handled one level up
    # by the singleton self-heal in api.py (rebuild on ConnectionError).
    #
    # Deliberately NO `retry=`: falkordb 1.6.1's cluster-detection probe copies
    # these connection_kwargs into a *synchronous* redis client, so an async
    # Retry object would be called sync and break construction. Do not re-add it.
    falkor = FalkorDB(
        host=cfg.falkordb_host,
        port=cfg.falkordb_port,
        password=cfg.falkordb_password,
        health_check_interval=cfg.falkordb_health_check_interval,
        socket_keepalive=True,
        socket_connect_timeout=cfg.falkordb_socket_connect_timeout,
        socket_timeout=cfg.falkordb_socket_timeout,
    )
    driver = FalkorDriver(
        falkor_db=falkor,
        # database == group_id: graphiti names the FalkorDB graph after the
        # group_id, and the driver connects per-graph. The injected client above
        # supplies the connection; `database` still selects the graph (it is
        # passed on every GRAPH.QUERY), so selection stays deterministic.
        database=cfg.group_id,
    )
    llm = AnthropicClient(
        config=LLMConfig(
            api_key=cfg.anthropic_api_key,
            model=cfg.llm_model,
            temperature=cfg.llm_temperature,
            max_tokens=cfg.llm_max_tokens,
        )
    )
    embedder = VoyageAIEmbedder(
        config=VoyageAIEmbedderConfig(
            api_key=cfg.voyage_api_key,
            embedding_model=cfg.embed_model,
            embedding_dim=cfg.embed_dim,
        )
    )
    # cross_encoder left as default (OpenAIRerankerClient). It is never
    # invoked unless a search recipe asks for cross-encoder reranking; our
    # recall path uses RRF + hub traversal, so no OpenAI call is made. The
    # placeholder OPENAI_API_KEY in compose lets its constructor succeed.
    return Graphiti(graph_driver=driver, llm_client=llm, embedder=embedder)


@lru_cache(maxsize=1)
def cached_entity_types() -> dict[str, type[BaseModel]]:
    return build_entity_types()


@lru_cache(maxsize=1)
def cached_edge_types() -> dict[str, type[BaseModel]]:
    return DEFAULT_EDGE_TYPES


@lru_cache(maxsize=1)
def cached_edge_type_map() -> dict[tuple[str, str], list[str]]:
    return DEFAULT_EDGE_TYPE_MAP
