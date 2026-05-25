# Graph engine

Brainbot uses [**Graphiti**](https://github.com/getzep/graphiti) (Apache 2.0) as the extraction and storage layer over the graph DB.

## What Graphiti does

- Takes an episode (text + metadata) and runs an LLM to extract entities and edges.
- Merges extracted entities into the existing graph using embedding-based dedup.
- Stores everything as a bi-temporal property graph in FalkorDB ([graph-database.md](./graph-database.md)).
- Exposes search, get-by-id, add-episode, and related operations over an HTTP API.
- Ships an official MCP server, which is how Claude Code talks to it ([mcp-integration.md](./mcp-integration.md)).

## Why Graphiti

The "LLM extracts entities and edges on every write" pipeline is the part we don't want to build ourselves. Graphiti's primitive (bi-temporal property graph with string-typed nodes/edges, no schema migrations) is exactly the right shape for the memory model ([memory-model.md](./memory-model.md)).

Schema-flexible: nodes and edges are strings, not enum types, so the graph can grow new kinds of facts without code changes. The MCP server already exists. License is Apache 2.0. The integration with FalkorDB is the project's default backend.

## Alternatives considered

- **Roll our own extraction + storage.** Full control, but 6+ months of work to reach what Graphiti does out of the box.
- **LangGraph / LlamaIndex memory abstractions.** Heavier, more opinionated, less aligned with the bi-temporal-facts model.
- **Vector store alone.** Already ruled out by the memory-model decision.
