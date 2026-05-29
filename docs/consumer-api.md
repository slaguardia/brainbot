# Consumer API reference

Exhaustive per-tool reference for every operation the brain exposes. The doc you keep open in another tab while writing a consumer.

For the narrative explanation (how-to, gotchas, the *why*), see [`consumer-integration.md`](./consumer-integration.md). This doc is the **spec**, not the tutorial.

All examples below show the JSON-RPC `params.arguments` shape — what your client (or `mcpCall`-equivalent helper) passes inside a `tools/call`. The wire framing around it is documented in [`consumer-integration.md`](./consumer-integration.md#whats-actually-on-the-wire--and-why-you-dont-care).

---

## All tools at a glance

| Tool | What it does | Read / write | Sync? |
|---|---|---|---|
| [`add_memory`](#add_memory) | Submit an episode for entity extraction | write | async (returns immediately, extraction runs server-side) |
| [`search_nodes`](#search_nodes) | Find entities matching a query | read | sync |
| [`search_memory_facts`](#search_memory_facts) | Find typed relational facts matching a query | read | sync |
| [`get_episodes`](#get_episodes) | Pull raw recent episodes | read | sync |
| [`get_entity_edge`](#get_entity_edge) | Look up a fact (edge) by UUID | read | sync |
| [`delete_entity_edge`](#delete_entity_edge) | Remove a fact by UUID | write | sync (destructive) |
| [`delete_episode`](#delete_episode) | Remove an episode by UUID | write | sync (destructive) |
| [`clear_graph`](#clear_graph) | Wipe everything in one or more groups | write | sync (destructive) |
| [`get_status`](#get_status) | Server + database connection health | read | sync |
| [`GET /health`](#get-health) (non-MCP) | Liveness probe for load balancers | read | sync |

The brain shape stays stable across these — every read returns `{"message": "...", <records>}` plus an `ErrorResponse` failure shape. Tool versions are pinned with the image (`GRAPHITI_REF=v0.29.1`); contract changes will be release-noted before being bumped.

---

## `add_memory`

Submit an episode to the brain. The server queues it and runs entity extraction asynchronously.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | `string` | yes | — | Human-readable label for the episode. Shown in `get_episodes`. |
| `episode_body` | `string` | yes | — | The actual content. For `source="json"`, this is a JSON-string-encoded JSON object (escape your braces). |
| `group_id` | `string` | no | server default (`"brain"` in our deployment) | Namespace boundary. **Avoid `-`** (RediSearch treats it as NOT and breaks extraction silently). Stick to alphanumeric + underscore. |
| `source` | `string` | no | `"text"` | One of `"text"`, `"json"`, `"message"`. Determines how Graphiti parses the body. |
| `source_description` | `string` | no | `""` | Free-text provenance label (e.g., `"ingest-cli"`, `"scout-verdict"`, `"slack-importer"`). Surfaced in `get_episodes` for debugging. |
| `uuid` | `string` | no | server-generated | Pre-assign the episode UUID. Mostly useful for re-runs / dedup pipelines. |

### Returns (success)

```json
{
  "message": "Episode 'Today's note' queued for processing in group 'brain'"
}
```

Returns **immediately** — before extraction runs. The episode is in the queue, not yet searchable.

### Returns (error)

```json
{ "error": "<error message>" }
```

Common causes:
- `"Services not initialized"` — server still starting up
- `"Error queuing episode: ..."` — usually downstream (FalkorDB unreachable, LLM provider 401)

### Behavior notes

- **Asynchronous extraction.** The episode is searchable typically 2–10s after queuing for short content, longer for long episodes. Poll `search_nodes` if you need to wait.
- **Cost.** Each episode triggers one LLM extraction call (Anthropic Haiku in our config) plus a burst of embedder calls (Voyage). Roughly $0.0016 per typical episode at current pricing — multiply by the number of episodes you're about to enqueue.
- **Per-group serialization.** Episodes within the same `group_id` are processed sequentially server-side to avoid race conditions during entity dedup. Different groups extract in parallel.

### Example

```json
{
  "name": "Meeting: Beatrice at Globex",
  "episode_body": "Talked to Beatrice from Globex today. She's worried about Redpanda's operational cost as a Kafka replacement.",
  "group_id": "brain",
  "source": "text",
  "source_description": "manual-input"
}
```

---

## `search_nodes`

Find entity nodes (people, organizations, topics, etc.) matching a natural-language query.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | `string` | yes | — | Natural language. Vector-embedded server-side; matching is semantic, not exact. |
| `group_ids` | `string[]` | no | `[server default group]` | Which namespaces to search. Pass `["brain"]` for your real data; `["my-test"]` for sandbox. |
| `max_nodes` | `integer` | no | `10` | Cap on returned results. |
| `entity_types` | `string[]` | no | `null` (all) | Narrow by entity label. Known labels in our config: `Person`, `Organization`, `Location`, `Event`, `Document`, `Topic`. See `compose/graphiti-config.yaml`. |

### Returns (success)

```json
{
  "message": "Nodes retrieved successfully",
  "nodes": [
    {
      "uuid": "f1e2d3c4-...",
      "name": "Beatrice",
      "labels": ["Entity", "Person"],
      "created_at": "2026-05-25T22:30:18.421000+00:00",
      "summary": "VP of platform engineering at Globex Industries, evaluating Kafka alternatives.",
      "group_id": "brain",
      "attributes": { /* arbitrary extras; embedding fields are stripped */ }
    }
  ]
}
```

If nothing matched: `{"message": "No relevant nodes found", "nodes": []}`.

### Returns (error)

`{ "error": "..." }` — same shape as `add_memory`. Common causes: Graphiti service not initialized, embedder 401/429 (Voyage), database unreachable.

### Behavior notes

- **Fuzzy by design.** `search_nodes("Beatrice")` may return adjacent entities (her organization, projects she's involved in). Use `entity_types=["Person"]` to narrow, or filter client-side on `name` for exact match.
- **Hybrid ranking.** Uses Graphiti's `NODE_HYBRID_SEARCH_RRF` recipe — reciprocal rank fusion across vector similarity and BM25 keyword match. You get both "semantically close" and "name-overlap" hits in one pass.
- **No embedding leakage.** Any `*_embedding` attributes on the underlying node are stripped before return.

### Example

```json
{ "query": "Beatrice", "group_ids": ["brain"], "max_nodes": 5, "entity_types": ["Person"] }
```

---

## `search_memory_facts`

Find **typed relational facts** — natural-language statements that link two entities — matching a query. Use this when the answer lives in a *relationship* rather than in any single node's properties.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | `string` | yes | — | Natural language. |
| `group_ids` | `string[]` | no | `[server default group]` | Which namespaces to search. |
| `max_facts` | `integer` | no | `10` | Must be positive — `0` or negative returns an error. |
| `center_node_uuid` | `string` | no | `null` | If set, bias the search toward facts near this node. Useful for "tell me about everything connected to Alice." |

### Returns (success)

```json
{
  "message": "Facts retrieved successfully",
  "facts": [
    {
      "uuid": "e1f2g3h4-...",
      "name": "RELATES_TO",
      "fact": "Beatrice is the new VP of platform engineering at Globex Industries",
      "valid_at": "2026-05-25T22:30:18+00:00",
      "invalid_at": null,
      "source_node_uuid": "<Beatrice uuid>",
      "target_node_uuid": "<Globex uuid>"
    }
  ]
}
```

Bi-temporal kicker: `invalid_at` is `null` for currently-true facts; when a newer episode contradicts an older fact, the old one gets `invalid_at` stamped (not deleted), so historical queries still work.

If nothing matched: `{"message": "No relevant facts found", "facts": []}`.

### Returns (error)

`{ "error": "max_facts must be a positive integer" }` or the standard error shape.

### Behavior notes

- **Same ranking primitive as `search_nodes`** — RRF hybrid. The difference is what's returned (edges/facts vs nodes).
- **Use this over `search_nodes` when the question is relational.** "Who works at Globex?" → `search_memory_facts`. "What do we know about Globex?" → `search_nodes` followed by drill-down.

### Example

```json
{ "query": "Beatrice job role", "group_ids": ["brain"], "max_facts": 10 }
```

---

## `get_episodes`

Pull raw recent episodes (the input text before extraction). Useful for debugging extraction quality, building a recency-ordered feed, or showing a user what they've recently fed in.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `group_ids` | `string[]` | no | `[server default group]` | Which namespaces. |
| `max_episodes` | `integer` | no | `10` | Cap on returned results. |

### Returns (success)

```json
{
  "message": "Episodes retrieved successfully",
  "episodes": [
    {
      "uuid": "a1b2c3...",
      "name": "Meeting: Beatrice at Globex",
      "content": "Talked to Beatrice from Globex today...",
      "created_at": "2026-05-25T22:30:18.421000+00:00",
      "source": "text",
      "source_description": "manual-input",
      "group_id": "brain"
    }
  ]
}
```

If empty: `{"message": "No episodes found", "episodes": []}`.

If you pass `group_ids: []` (explicit empty list) you'll currently get an empty result — there's no "all groups" mode here.

### Behavior notes

- Episodes are returned **most-recent-first** by created_at within each group.
- The `content` field is the verbatim `episode_body` you passed to `add_memory`. Nothing is summarized or truncated server-side.

---

## `get_entity_edge`

Look up a single fact (edge between two entities) by its UUID.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `uuid` | `string` | yes | — | UUID of the edge to retrieve. Usually obtained from a prior `search_memory_facts` call. |

### Returns (success)

A single fact dict in the same shape as one entry from `search_memory_facts.facts`:

```json
{
  "uuid": "e1f2g3h4-...",
  "name": "RELATES_TO",
  "fact": "Beatrice is the new VP of platform engineering at Globex Industries",
  "valid_at": "2026-05-25T22:30:18+00:00",
  "invalid_at": null,
  "source_node_uuid": "<source uuid>",
  "target_node_uuid": "<target uuid>"
}
```

### Returns (error)

`{ "error": "..." }` — typically a database error if the UUID doesn't exist.

---

## `delete_entity_edge`

Remove a fact (edge) by UUID. **Destructive — there is no undo.**

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `uuid` | `string` | yes | — | UUID of the edge to delete. |

### Returns (success)

```json
{ "message": "Entity edge with UUID <uuid> deleted successfully" }
```

### Behavior notes

- Prefer **not deleting** facts in normal operation. The bi-temporal model is designed so newer episodes *invalidate* (set `invalid_at`) older facts cleanly. Hard delete loses the historical trail.
- Reserve this for: spam ingest, corrupt extraction, GDPR-style removal.

---

## `delete_episode`

Remove an episode by UUID. **Destructive — does not roll back extracted entities or facts.**

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `uuid` | `string` | yes | — | UUID of the episode (from `get_episodes`). |

### Returns (success)

```json
{ "message": "Episode <uuid> deleted successfully" }
```

### Behavior notes

- Deleting an episode does **not** un-extract its entities or facts. Those stay in the graph (attached to other episodes if they were re-mentioned, or orphaned).
- Use sparingly. Same guidance as `delete_entity_edge`.

---

## `clear_graph`

Wipe everything in one or more groups. **Catastrophically destructive.**

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `group_ids` | `string[]` | no | `[server default group]` | Which groups to wipe. Pass an explicit list to be safe. |

### Returns (success)

```json
{ "message": "Graph data cleared successfully for group IDs: brain" }
```

### Returns (error)

```json
{ "error": "No group IDs specified for clearing" }
```

(Server refuses if it can't resolve a target group from arguments or default config.)

### Behavior notes

- This is what `scripts/reset_brain.py` runs under the hood for `--graph smoketest`.
- Consumers should not call this in normal operation. Reserve for `reset_brain.py`-style operator workflows.
- **There is no "are you sure" prompt server-side.** Wire your own guard rails on the caller side.

---

## `get_status`

Health check that includes a real database round-trip. Heavier than `/health`; use it when you want to confirm the brain is end-to-end functional.

### Arguments

None.

### Returns

```json
{
  "status": "ok",
  "message": "Graphiti MCP server is running and connected to falkordb database"
}
```

On failure:
```json
{
  "status": "error",
  "message": "Graphiti MCP server is running but database connection failed: <reason>"
}
```

### Behavior notes

- Runs `MATCH (n) RETURN count(n)` server-side, so it can be slow under heavy load.
- For a cheap liveness probe (load balancer, container healthcheck), use `GET /health` instead.

---

## `GET /health` (non-MCP)

Plain HTTP. Not a `tools/call`. Used by Docker healthchecks and load balancers.

### Request

```http
GET /health HTTP/1.1
```

### Returns

```json
{ "status": "healthy", "service": "graphiti-mcp" }
```

Status `200` if the process is up. Does **not** verify database connectivity — use `get_status` for that.

---

## Error shape (cross-tool)

Every tool returns either its typed success shape or an `ErrorResponse`:

```json
{ "error": "<human-readable message>" }
```

The HTTP status of the underlying JSON-RPC call is typically `200` even when `error` is set — the *MCP-level* result carries the failure. Your client should:

1. Check for HTTP non-2xx → transport/auth problem (timeout, bad bearer, server down)
2. Check for `error` key in the parsed MCP result → tool-level failure (validation, database, downstream LLM)
3. Otherwise consume the success shape

The Python `GraphitiClient` at `migrate/graphiti_clients.py` raises `RuntimeError` on either condition; the TypeScript recipe in [`consumer-integration.md`](./consumer-integration.md#typescript--other-languages) throws.

---

## Things not covered here

- **Reranking variants** — Graphiti has reranked-search recipes (`NODE_HYBRID_SEARCH_CROSS_ENCODER`, etc.). They require an `OpenAIRerankerClient` to be configured server-side, which our deployment intentionally stubs with a placeholder key. Calling them will hit a 401. Don't use reranking until that's fixed (or set a real `OPENAI_API_KEY` in `compose/.env`).
- **Batch operations** — there's no `add_memory_batch` here. The way to batch is: call `add_memory` N times in a loop. Per-group serialization on the server side already prevents races.
- **Auth granularity** — there's currently one bearer token per brain. No per-tool permissions, no per-consumer keys, no rate limits. If/when these matter, they'll be added at the Caddy layer.

---

## Where this contract lives

- **Upstream Graphiti MCP server source** at the pinned tag: <https://github.com/getzep/graphiti/blob/v0.29.1/mcp_server/src/graphiti_mcp_server.py>
- **Our pinned version:** `GRAPHITI_REF=v0.29.1` in `compose/docker-compose.yml`. Contract changes when this bumps.
- **Reference clients:**
  - Python: [`migrate/graphiti_clients.py`](../migrate/graphiti_clients.py)
  - TypeScript: the recipe in [`consumer-integration.md`](./consumer-integration.md#typescript--other-languages)
  - Go: [`scout/internal/brainbot/client.go`](https://github.com/stevenlaguardia/scout/blob/main/internal/brainbot/client.go) (third-party — first external consumer)
