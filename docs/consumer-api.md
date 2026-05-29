# Consumer API reference

Exhaustive reference for every operation the brain exposes. The doc you keep open in another tab while writing a consumer.

For the narrative (how-to, gotchas, the *why*), see [`consumer-integration.md`](./consumer-integration.md). This doc is the **spec**, not the tutorial.

The brain deliberately exposes a **small surface — three operations** — over two transports:

- **Plain HTTP/JSON** (`POST /capture`, `GET /recall`, `GET /profile`, `GET /health`). The simplest path; use this for typed consumers. No session handshake.
- **MCP** (streamable HTTP at `/mcp`): the same three operations as tools `capture`, `recall`, `profile`, for Claude Code and other LLM-tool-discovery harnesses.

Both faces are served by the one `brain` service (`brain/api.py`) and share one `Brain` instance. The rich graph-introspection surface of the old standalone Graphiti MCP server (`add_memory`, `search_nodes`, `delete_*`, `clear_graph`, …) is **not** exposed — the brain narrowed the contract to capture/recall/profile on purpose (see `brain/README.md`).

---

## All operations at a glance

| Operation | HTTP | MCP tool | Read/write | Sync? |
|---|---|---|---|---|
| [Capture](#capture) | `POST /capture` | `capture` | write | async extraction (returns after enqueue+extract; see notes) |
| [Recall](#recall) | `GET /recall` | `recall` | read | sync |
| [Profile](#profile) | `GET /profile` | `profile` | read | sync |
| [Health](#health) | `GET /health` | — | read | sync |

---

## Capture

Decompose raw text into named-subject, domain-explicit atomic facts, then ingest them (the body episode + one episode per fact), applying the brain's extraction tuning.

### HTTP

```http
POST /capture HTTP/1.1
Content-Type: application/json

{ "text": "Talked to Beatrice from Globex today; she's worried about Kafka op cost." }
```

### MCP

Tool `capture`, arguments: `{ "text": "<string>" }`.

### Arguments

| Name | Type | Required | Notes |
|---|---|---|---|
| `text` | `string` | yes | The raw content. First-person ("I", "me", "my") is bound to `BRAIN_USER_NAME` during decomposition. Whitespace-only is rejected. |

### Returns (success)

HTTP `202`; MCP returns the same object:

```json
{ "mode": "decomposed", "episodes": 4, "topic": "Globex / Kafka cost concern", "facts": 3 }
```

- `mode` — `"decomposed"` normally, or `"raw"` if `BRAIN_DECOMPOSE_ENABLED=false`.
- `episodes` — total episodes written (`1` body + `N` facts; `1` in raw mode).
- `topic` — the decomposer's short label for the body episode (`null` in raw mode).
- `facts` — number of atomic-fact episodes written (`0` in raw mode).

### Returns (error)

HTTP `400` (and `ValueError` surfaced as `400`):

```json
{ "error": "text is required" }
```

Causes: empty/whitespace `text`, or invalid JSON body.

### Behavior notes

- **Capture awaits the pipeline.** Unlike the old async `add_memory`, `/capture` runs decompose (one Claude call) + `1+N` `add_episode` extraction passes before returning — seconds, not milliseconds. Consumers that need instant UX should ack optimistically and fire-and-forget (the PWA does exactly this).
- **Cost.** One decomposition call (Sonnet by default) + one extraction call per episode (Haiku) + embedder calls (Voyage). Roughly a cent per typical capture; bursts add up.
- **Per-group serialization** still applies inside graphiti-core during dedup.

---

## Recall

Targeted retrieval for a question. Hybrid edge search (RRF: BM25 + vector) selects candidate facts, then each is scored by absolute cosine similarity between the query embedding and the fact embedding.

### HTTP

```http
GET /recall?q=what%20does%20the%20user%20want%20in%20a%20job&limit=8 HTTP/1.1
```

### MCP

Tool `recall`, arguments: `{ "query": "<string>", "limit": 20 }`.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `q` (HTTP) / `query` (MCP) | `string` | yes | — | Natural-language question. |
| `limit` | `integer` | no | `20` | Max facts to return. |

### Returns (success)

MCP `recall` returns the **list** directly. HTTP wraps it:

```json
{
  "query": "what does the user want in a job",
  "count": 2,
  "facts": [
    {
      "fact": "The user wants a forward-deployed engineering role with direct customer contact.",
      "name": "WANTS",
      "score": 0.7421,
      "valid_at": "2026-05-25T22:30:18+00:00",
      "invalid_at": null
    }
  ]
}
```

Each fact record:

| Field | Type | Notes |
|---|---|---|
| `fact` | `string` | The natural-language fact (carries its own domain context — the graph is hub-shaped). |
| `name` | `string` | Edge label (e.g. `WANTS`, `RELATES_TO`). |
| `score` | `float` | Absolute on-target cosine in ~`[0,1]`. **The brain does not threshold** — the consumer decides what's strong enough. All-low scores mean the brain doesn't really know this. |
| `valid_at` | `string\|null` | When the fact became true (ISO 8601). |
| `invalid_at` | `string\|null` | When it was superseded; `null` for currently-true facts. |

Empty result: HTTP `{ "query": ..., "count": 0, "facts": [] }`; MCP `[]`.

### Returns (error)

HTTP `400 { "error": "q is required" }` when `q` is missing/blank. (`limit` is coerced to `20` if unparseable, not an error.)

### Behavior notes

- **Scored, not filtered.** Use `score` to gate relevance in your consumer; the brain reports, it doesn't decide.
- **Hub topology.** Node-distance reranking doesn't help (every concept is ~2 hops from every other through the user node), so recall uses RRF + per-fact cosine rather than graph distance.

---

## Profile

Full-profile dump: every **currently-true** fact about the user, unscored, newest first. Use when you need the whole picture rather than the answer to one question (the blind-spot fix at current scale — the consumer reasons over the entire profile).

### HTTP

```http
GET /profile HTTP/1.1
```

### MCP

Tool `profile`, no arguments.

### Returns (success)

MCP returns the **list**; HTTP wraps it:

```json
{
  "count": 1,
  "facts": [
    { "fact": "The user is migrating off Kafka.", "name": "RELATES_TO", "valid_at": "2026-05-25T22:30:18+00:00", "invalid_at": null }
  ]
}
```

Same fact shape as recall **minus `score`** (profile is a dump, not a ranked search). Bi-temporally superseded facts (`expired_at` set) are excluded.

### Behavior notes

- Can be large as the brain grows. For targeted questions prefer `recall`.

---

## Health

Liveness probe. Plain HTTP only — not an MCP tool.

```http
GET /health HTTP/1.1
```

```json
{ "ok": true }
```

`200` if the process is up. Brain construction is lazy, so this does **not** verify FalkorDB/LLM connectivity — it's a cheap liveness check for the Docker healthcheck and load balancers.

---

## Error shape

HTTP errors carry a non-2xx status and `{ "error": "<message>" }`. Your consumer should:

1. Check HTTP status — non-2xx is a transport/validation/auth problem.
2. On 2xx, consume the documented success shape.

For MCP, tool errors surface as the MCP result's error field (HTTP framing is typically `200`); the reference clients raise on either condition.

---

## Reference clients

- **Python:** [`migrate/graphiti_clients.py`](../migrate/graphiti_clients.py) — a thin `BrainClient` over the HTTP routes (`capture`, `recall`, `profile`). (Filename is historical; it predates the brain-service rename.)
- **TypeScript:** the minimal recipe in [`consumer-integration.md`](./consumer-integration.md#typescript--other-languages).
- **Claude Code (MCP):** [`templates/claude-code-client/INSTALL.md`](../templates/claude-code-client/INSTALL.md) wires the brain's `/mcp` face into a project's `.mcp.json`.

The contract version tracks the brain service, not an upstream image: the brain pins `graphiti-core==0.29.1` in `brain/pyproject.toml`, but the operations above (`capture`/`recall`/`profile`) are the brain's own surface and are stable across graphiti-core patches.
