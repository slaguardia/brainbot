# MCP integration

The Graphiti MCP server is wired into **Claude Code** (the terminal harness). The **PWA bypasses MCP** and talks directly to Graphiti's REST endpoint over the docker network.

## Why split

MCP is the right protocol for terminal-tool integration:

- Claude Code's tool list is dynamic and model-aware.
- Tools are JSON-shaped and benefit from a standard transport.
- Auth, schemas, and tool discovery are exactly what MCP solves.

The PWA is a single Node process running on the same host as Graphiti. Routing its calls through MCP would mean serializing/deserializing JSON over an extra hop for zero gain.

## The principle

Use MCP where you're getting the protocol's actual benefits. Don't use it as a default just because it's available.

## Current wiring

- **Claude Code → Graphiti MCP server.** Configured via `.mcp.json` in the client repo. Bearer token over HTTPS to the VPS.
- **PWA → Graphiti REST.** Direct HTTP inside the docker network. No auth between containers (network isolation handles it).
- **Hook (`inject_memory.py`).** Runs on every user-prompt-submit event in Claude Code. Calls `search_nodes` via MCP and injects up to 2KB of matched-node context into the prompt. Hard-capped to keep behavior predictable; silently degrades if the brain is unreachable.

Setup: [INSTALL.md](../INSTALL.md).

## Alternatives considered

- **MCP everywhere.** Rejected — adds latency and a serialization layer for no protocol benefit inside the PWA process.
- **Direct REST from Claude Code.** Rejected — would lose dynamic tool discovery, schema validation, and standard auth handling.
