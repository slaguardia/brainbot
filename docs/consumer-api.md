# Consumer API reference

> **Historical (graph contract).** This documents the old
> `capture` / `recall` / `profile`-over-graphiti contract (`POST /capture`,
> scored facts, episode bodies). The **live contract is now**
> `recall(query, scope)` / `profile(scope)` / `map(scope)` returning chunks and a
> `Context`, plus `POST /ingest {url}` — over Postgres + pgvector, no graph. The
> current spec is in [`../brain/README.md`](../brain/README.md) and
> [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md).

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

Rewrite raw text into faithful, named-subject prose and ingest it as **one episode**, applying the brain's extraction tuning. The override-tuned extractor pulls the typed entities and facts (each with `polarity`/`strength`) from that single episode — no per-fact fan-out.

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
{ "mode": "rewrite", "episodes": 1, "topic": "Globex / Kafka cost concern" }
```

- `mode` — `"rewrite"` normally, or `"raw"` if `BRAIN_DECOMPOSE_ENABLED=false`.
- `episodes` — always `1`: the capture is rewritten into a single episode (no per-fact fan-out); the extractor pulls the entities and facts from it.
- `topic` — the decomposer's short label for the episode (`null` in raw mode).

### Returns (error)

HTTP `400` (and `ValueError` surfaced as `400`):

```json
{ "error": "text is required" }
```

Causes: empty/whitespace `text`, or invalid JSON body.

### Behavior notes

- **Capture awaits the pipeline.** Unlike the old async `add_memory`, `/capture` runs decompose (one Claude call) + a single `add_episode` extraction pass (entities, fact-edges, and a per-edge attribute pass for `polarity`/`strength`) before returning — seconds, not milliseconds. Consumers that need instant UX should ack optimistically and fire-and-forget (the PWA does exactly this).
- **Cost.** One decomposition call (Sonnet by default) + extraction (Haiku) + embedder calls (Voyage). Roughly a cent per typical capture; bursts add up.
- **Per-group serialization** still applies inside graphiti-core during dedup.

---

## Recall

Targeted retrieval for a question. Hybrid edge search (RRF: BM25 + vector) selects candidate facts, then each is scored by absolute cosine similarity between the query embedding and the fact embedding.

### HTTP

```http
GET /recall?q=what%20does%20the%20user%20want%20in%20a%20job&limit=8 HTTP/1.1
```

### MCP

Tool `recall`, arguments: `{ "query": "<string>", "limit": 20, "debug": false }`.

### Arguments

| Name | Type | Required | Default | Notes |
|---|---|---|---|---|
| `q` (HTTP) / `query` (MCP) | `string` | yes | — | Natural-language question. |
| `limit` | `integer` | no | `20` | Max facts to return. |
| `debug` | `boolean` | no | `false` | When true, also returns the source `episodes` (provenance/human-tracing only — **not** a knowledge surface). HTTP: `?debug=true`. |

### Returns (success)

Facts only by default — the graph is the source of truth, so recall returns scored graph facts and **no episodes**. MCP `recall` returns the object `{ "facts": [...] }`; HTTP wraps it with `query` and `fact_count`:

```json
{
  "query": "what does the user want in a job",
  "facts": [
    {
      "fact": "The user wants a forward-deployed engineering role with direct customer contact.",
      "name": "WANTS",
      "score": 0.7421,
      "polarity": "positive",
      "strength": "hard",
      "valid_at": "2026-05-25T22:30:18+00:00",
      "invalid_at": null
    }
  ],
  "fact_count": 1
}
```

Each fact record:

| Field | Type | Notes |
|---|---|---|
| `fact` | `string` | The natural-language fact (carries its own domain context — the graph is hub-shaped). |
| `name` | `string` | Edge label (e.g. `WANTS`, `RELATES_TO`). |
| `score` | `float` | Absolute on-target cosine in ~`[0,1]`. **The brain does not threshold** — the consumer decides what's strong enough. All-low scores mean the brain doesn't really know this. |
| `polarity` | `string\|null` | `"positive"` or `"negative"` — negatives (avoidances, "doesn't want…") are first-class facts, not absences. `null` on facts the extractor didn't tag. |
| `strength` | `string\|null` | `"hard"` or `"soft"` — how firmly the fact is held (a hard rule vs. a soft preference). `null` on facts the extractor didn't tag. |
| `valid_at` | `string\|null` | When the fact became true (ISO 8601). |
| `invalid_at` | `string\|null` | When it was superseded; `null` for currently-true facts. |

Empty result: HTTP `{ "query": ..., "facts": [], "fact_count": 0 }`; MCP `{ "facts": [] }`.

### Returns (debug)

With `?debug=true` (HTTP) / `"debug": true` (MCP), the source episode bodies are re-included for provenance/human tracing — they are **not** a knowledge surface (the graph is). HTTP adds `episodes` + `episode_count`; MCP adds `episodes`:

```json
{
  "query": "what does the user want in a job",
  "facts": [ … ],
  "fact_count": 1,
  "episodes": [
    { "name": "Globex / Kafka cost concern", "body": "<the captured episode text>" }
  ],
  "episode_count": 1
}
```

### Returns (error)

HTTP `400 { "error": "q is required" }` when `q` is missing/blank. (`limit` is coerced to `20` if unparseable, not an error.)

### Behavior notes

- **Scored, not filtered.** Use `score` to gate relevance in your consumer; the brain reports, it doesn't decide.
- **Negatives and gates are facts.** The extractor captures negatives and hard-held rules as first-class facts tagged via `polarity`/`strength`, so the graph facts are legible on their own — there's no need to read episode bodies to recover what the user *doesn't* want or what's a hard rule.
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

A flat list of current graph facts — not episode bodies. MCP `profile` returns the object `{ "facts": [...] }`; HTTP wraps it with `count`:

```json
{
  "count": 1,
  "facts": [
    { "fact": "The user is migrating off Kafka.", "name": "RELATES_TO", "polarity": "positive", "strength": "soft", "valid_at": "2026-05-25T22:30:18+00:00" }
  ]
}
```

Each fact carries `fact`, `name`, `polarity`, `strength`, and `valid_at` (same `polarity`/`strength` semantics as [recall](#recall); `null` when the extractor didn't tag). No `score` (profile is a dump, not a ranked search) and no `invalid_at` — only currently-true facts are returned: those whose `invalid_at`/`expired_at` IS NULL (not bi-temporally superseded).

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
