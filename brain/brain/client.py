"""Construct graphiti-core directly — no MCP server.

This is the architectural keystone: the brain owns its Graphiti instance
and gets full access to add_episode params (custom_extraction_instructions,
entity_types, edge_types) and the search_() recipe system — all of which
the MCP server hides.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel
from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.voyage import VoyageAIEmbedder, VoyageAIEmbedderConfig

from .config import Config, DEFAULT_ENTITY_TYPES


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
    driver = FalkorDriver(
        host=cfg.falkordb_host,
        port=cfg.falkordb_port,
        password=cfg.falkordb_password,
        # database == group_id: graphiti names the FalkorDB graph after the
        # group_id, and the driver connects per-graph. They must match.
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
