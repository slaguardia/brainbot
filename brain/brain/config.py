"""Brain service configuration — all from env, with sane defaults.

The brain service constructs graphiti-core directly (no MCP server in the
loop). It runs on the same docker network as falkordb. See brain/README.md
for the architecture rationale (the research that led here lives in the
Phase 2 conversation notes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# Default extraction override. graphiti-core's stock extraction prompt is
# tuned for Wikipedia-style NER and explicitly refuses abstract concepts
# ("NEVER extract abstract concepts", "When in doubt, do NOT extract").
# For a personal brain that's exactly backwards — a person's values, goals,
# and preferences ARE the point. This instruction is appended to the
# extraction prompt and pushes back. Validated: 2 -> 20 entities on the
# same input.
DEFAULT_EXTRACTION_INSTRUCTIONS = """\
ADDITIONAL EXTRACTION INSTRUCTIONS — these take precedence over the conservative defaults above.

This is a personal knowledge graph. Its owner is actively curating it and wants comprehensive structured recall, so the "When in doubt, do NOT extract" rule does NOT apply.

DO extract as Topic entities (in addition to all other entity types) any specific, named thing the text asserts, across ANY area of life (work, health, relationships, hobbies, learning, money, home, beliefs — no domain is privileged):
- Abstract concepts, when specific enough to name. Qualify vague ones by their domain so concepts that share a word stay distinct (e.g. "consistency" mentioned about exercise and "consistency" mentioned about a writing habit are two different concepts, not one).
- Values, preferences, opinions, and stances.
- Goals, aspirations, intentions, and constraints.
- Skills, methods, practices, and named approaches.
- Categories, fields, or kinds of things the owner likes, dislikes, seeks, or avoids.
- Named technologies, tools, works, products, or techniques, even when not notable enough for a Wikipedia article.

The guiding test is NOT "could this have a Wikipedia article?" but "is this a specific thing the owner would want their brain to remember and connect to other things?" If yes, extract it.

Still DO NOT extract: bare unqualified generic words (e.g. "things", "stuff", "time", "people", "work"), pronouns, temporal information (dates, times, durations), or sentence fragments that wouldn't stand alone as a node name."""


# Entity types the extractor is told about. Each becomes a second node
# label alongside `Entity`. Kept deliberately generic — no Preference/Goal
# schema lock-in. The custom_extraction_instructions do the steering; these
# just give the classifier reasonable buckets.
DEFAULT_ENTITY_TYPES: dict[str, str] = {
    "Person": "Individual humans referenced by name",
    "Organization": "Companies, teams, institutions, formal groups",
    "Location": "Physical or virtual places",
    "Event": "Time-bound occurrences, meetings, milestones",
    "Document": "Articles, books, papers, threads, recorded content",
    "Topic": "A concept, value, preference, goal, skill, or subject the user cares about",
}


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Providers
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    voyage_api_key: str = field(default_factory=lambda: os.environ.get("VOYAGE_API_KEY", ""))

    # LLM (extraction + decomposition)
    llm_model: str = field(default_factory=lambda: os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5"))
    decompose_model: str = field(default_factory=lambda: os.environ.get("BRAIN_DECOMPOSE_MODEL", "claude-sonnet-4-5"))
    llm_temperature: float = field(default_factory=lambda: float(os.environ.get("BRAIN_LLM_TEMPERATURE", "1.0")))
    llm_max_tokens: int = field(default_factory=lambda: int(os.environ.get("BRAIN_LLM_MAX_TOKENS", "4096")))

    # Embedder
    embed_model: str = field(default_factory=lambda: os.environ.get("BRAIN_EMBED_MODEL", "voyage-3-lite"))
    embed_dim: int = field(default_factory=lambda: int(os.environ.get("BRAIN_EMBED_DIM", "512")))

    # FalkorDB. NOTE: `database` must equal the group_id — graphiti uses the
    # group_id as the FalkorDB graph name, and the driver connects per-graph.
    falkordb_host: str = field(default_factory=lambda: os.environ.get("FALKORDB_HOST", "falkordb"))
    falkordb_port: int = field(default_factory=lambda: int(os.environ.get("FALKORDB_PORT", "6379")))
    falkordb_password: str | None = field(default_factory=lambda: os.environ.get("FALKORDB_PASSWORD") or None)

    # Brain identity + namespace
    group_id: str = field(default_factory=lambda: os.environ.get("BRAIN_GROUP_ID", "brain"))
    user_name: str = field(default_factory=lambda: os.environ.get("BRAIN_USER_NAME", "the user"))

    # Behavior
    extraction_instructions: str = field(
        default_factory=lambda: os.environ.get("BRAIN_EXTRACTION_INSTRUCTIONS") or DEFAULT_EXTRACTION_INSTRUCTIONS
    )
    decompose_enabled: bool = field(default_factory=lambda: _bool("BRAIN_DECOMPOSE_ENABLED", True))

    def validate(self) -> None:
        missing = [
            n for n, v in (("ANTHROPIC_API_KEY", self.anthropic_api_key), ("VOYAGE_API_KEY", self.voyage_api_key))
            if not v
        ]
        if missing:
            raise RuntimeError(f"missing required env: {', '.join(missing)}")
