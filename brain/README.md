# brain service

The smart core. Constructs **graphiti-core directly** (no MCP server in the loop) and serves two operations over HTTP:

- `POST /capture {text}` — decompose raw text into named-subject, domain-explicit atomic facts, then ingest them with extraction tuning graphiti's stock prompts refuse.
- `GET /recall?q=&limit=` — hybrid edge search returning relevant facts for a consumer to synthesize.

## Why this exists (the architecture decision)

We started talking to graphiti through its **MCP server**. Research into graphiti-core v0.29.1 showed the MCP server is the bottleneck, not graphiti:

- It throws away `custom_extraction_instructions` (the hook that took concept extraction from 2 → 20 entities on the same input).
- It doesn't forward `excluded_entity_types`, `edge_types`, or `edge_type_map`.
- Its `search_nodes` tool hardcodes `NODE_HYBRID_SEARCH_RRF` with no center-node or cross-encoder option — the cause of muddy, domain-bleeding retrieval.

graphiti-core exposes all of it. So the brain calls graphiti-core directly and keeps the MCP server only for the Claude Code consumer (where MCP is the required protocol).

This is the project's own thesis made real: **one smart brain, many thin consumers.** The PWA backend is now a dumb proxy to this service.

## The capture pipeline

```
raw text
  → decompose (1 Claude call): rewrite to named-subject prose + emit atomic facts
  → add_episode(body)            # coherent original, vector-search anchor
  → add_episode(fact) × N        # each fact extracts into clean triples
       …all with custom_extraction_instructions + generic entity types
```

Two design choices, both validated in the Phase 2 spike:

1. **Decomposition** — graphiti's extractor works on named-subject, domain-explicit statements, not first-person preference prose. The decomposer rewrites input into that shape. First-person pronouns become `BRAIN_USER_NAME` so the brain knows who "I" is.
2. **Extraction override** — graphiti's stock prompt says *"NEVER extract abstract concepts."* For a personal brain that's backwards. `custom_extraction_instructions` (see `config.py`) pushes back; abstract domain-qualified concepts become first-class `Topic` entities.

## Recall

On a known-subject personal brain the graph is hub-shaped (everything hangs off the user node), so each fact already carries its domain context in the fact text. `recall()` does hybrid edge search (RRF) and returns the fact records; the consumer's LLM filters/synthesizes. Node-distance reranking doesn't help on a star topology (every concept is 2 hops from every other through the user) — that's why we use RRF + fact-text context rather than graph-distance.

## Config (env)

| Var | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required (extraction + decomposition) |
| `VOYAGE_API_KEY` | — | required (embeddings) |
| `FALKORDB_HOST` / `FALKORDB_PORT` | `falkordb` / `6379` | |
| `BRAIN_GROUP_ID` | `brain` | == the FalkorDB graph name (graphiti uses group_id as the graph) |
| `BRAIN_USER_NAME` | `the user` | who first-person captures are about |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5` | extraction model |
| `BRAIN_DECOMPOSE_MODEL` | `claude-sonnet-4-5` | decomposition model (quality matters more here) |
| `BRAIN_EMBED_MODEL` / `BRAIN_EMBED_DIM` | `voyage-3-lite` / `512` | bump to `voyage-3`/`1024` if retrieval needs sharper ranking |
| `BRAIN_EXTRACTION_INSTRUCTIONS` | (built-in) | override the extraction steering text |
| `BRAIN_DECOMPOSE_ENABLED` | `true` | set false to ingest raw text without decomposition |

## Run

```sh
# Local: brain runs in docker on the brainnet; exposed on 127.0.0.1:8100 via the local overlay.
cd compose
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d brain
curl -s localhost:8100/health
curl -s -X POST localhost:8100/capture -H 'Content-Type: application/json' -d '{"text":"..."}'
curl -s 'localhost:8100/recall?q=what%20does%20the%20user%20want&limit=8'
```

## Known gaps

- **Capture latency.** `/capture` awaits decompose + N extraction passes (seconds). Fine because consumers ack optimistically (the PWA) — but a background queue is the eventual fix for very large captures.
- **One conflation edge observed.** graphiti's dedup occasionally over-merges (a fitness "iterate" mention merged into the work "iteration velocity" node). Tracked; would be addressed by the read-before-write curation layer (the planned v3) or tighter dedup settings.
- **Retrieval bleed (~1 in 6).** RRF with voyage-3-lite occasionally surfaces an off-domain fact. Consumer LLM filters via fact text; sharper options are a bigger embedder or a cross-encoder reranker (both supported by graphiti-core, not yet wired).
