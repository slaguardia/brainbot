# Graph database

The graph lives in [**FalkorDB**](https://www.falkordb.com), a Redis module that speaks Cypher.

## Why FalkorDB

- ~6× more memory-efficient than Neo4j. Fits comfortably on a small VPS.
- It's Graphiti's default backend for the MCP server — the integration story is "just work" instead of "wire it up."
- Cypher-compatible, so the query model is familiar.
- Vector indexes are built in, which keeps the embedder pipeline ([embedder.md](./embedder.md)) simple.

## The honest tradeoff

Neo4j has more tooling around it (Bloom, Cypher Shell, Aura). FalkorDB is younger and the ecosystem is thinner. For a single-user system, the memory win matters more than the tooling depth. If we ever need Neo4j-specific tooling, Graphiti supports it as an alternative backend — config change, not a rewrite.

## Alternatives considered

- **Neo4j.** Industry-standard, mature, enormous ecosystem. Lost on memory footprint and on adding a step to the Graphiti integration.
