# Consumer integration guide

How your app talks to the brain. This doc is the canonical reference for anyone building a consumer app — read top to bottom if you've never used the brain before. Otherwise skip to the section you need.

---

## Quickstart — your first brain call in 5 minutes

If you have a brain running locally (see [README](../README.md) "Running it"), this gets you to a working call.

**1. Install the dep.** The client uses `requests`:
```sh
pip install requests
```

**2. Copy or import the client.** It lives at `migrate/graphiti_clients.py` in this repo. If you're building a consumer in a sibling project, copy the file (it's ~150 lines, stdlib + requests only, no transitive deps). If you're building inside this repo, just import it.

**3. Make your first call:**
```python
from graphiti_clients import GraphitiClient

brain = GraphitiClient(
    base_url="http://127.0.0.1:8000",   # local; use https://brain.api.{domain} for VPS
    bearer=None,                          # set to BRAIN_BEARER_TOKEN on VPS
    group_id="brain",                     # the default namespace
)

# Read: find entities matching a query
hits = brain.search_nodes(query="Beatrice", max_nodes=10)
for node in hits:
    print(node["name"], "→", node.get("summary", ""))

# Write: post an episode for extraction
brain.add_memory(
    name="Today's note",
    episode_body="Talked to Beatrice about migrating off Kafka.",
    source="text",
    source_description="manual-input",
)
```

That's the whole integration shape. The client handles the MCP session handshake under the hood; you just call typed methods.

**4. Verify it worked.** `add_memory` returns immediately — extraction is async on the server. Wait a few seconds, then `search_nodes("Beatrice")` should turn up the entity. Or look at the FalkorDB Browser at `http://127.0.0.1:3000` (graph dropdown → `brain` → `MATCH (n) RETURN n`).

---

## What you can call (the tool surface)

The brain exposes more than the two methods above, but in practice 90% of consumers only need these four. Detailed schemas and edge cases live in [`consumer-api.md`](./consumer-api.md) (planned, being written separately) — what's here is the working knowledge.

### `search_nodes(query, max_nodes=10, entity_types=None) → list[dict]`

**Use for:** finding entities (people, organizations, topics, etc.) that match a natural-language query. This is the workhorse read operation.

**Returns:** a list of entity nodes. Each has at least `name`, `summary`, `uuid`, plus a `labels` list of typed entity categories (`Person`, `Organization`, `Topic`, etc.). Empty list if nothing matched.

**Notes:** uses Voyage embeddings for vector match plus graph traversal. Results are ordered by relevance. `entity_types=["Person"]` narrows to a single category.

### `search_memory_facts(query, max_facts=10) → list[dict]`

**Use for:** finding **typed relational facts** — natural-language statements like "Beatrice is VP of platform engineering at Globex" — that match a query. Use this when the answer is in the *relationship between things*, not in any single entity's properties.

**Returns:** list of facts, each with `fact` (the natural-language string), `source_node`, `target_node`, `valid_at`, `invalidated_at`. The `invalidated_at` field is the bi-temporal kicker — old facts get superseded cleanly rather than overwritten.

### `add_memory(name, episode_body, source="text", source_description=None) → dict`

**Use for:** writing new content into the brain. The brain will run entity extraction on it asynchronously and merge the results into the existing graph.

**Behavior:** returns immediately with a queued-status acknowledgment. Extraction takes 2–10 seconds for short content, longer for long content. If you need to wait until your data is searchable, poll `search_nodes` for an expected entity.

**Cost:** one LLM extraction call per `add_memory` (roughly $0.0016 per typical episode with Claude Haiku). Burst this and you'll watch your provider dashboard.

### `get_episodes(group_id="brain", last_n=10) → list[dict]`

**Use for:** retrieving raw recent episodes (the input text, before extraction). Useful for debugging extraction quality or for showing a user "here's what's been ingested recently."

**Returns:** list of episode dicts with `name`, `content`, `source_description`, `created_at`.

### The full surface

The Graphiti MCP server exposes more tools (`delete_episode`, `delete_entity_edge`, `clear_graph`, `add_memory_batch`, plus reranking variants of the search calls). They're all callable through the same `GraphitiClient._call_tool` pattern but aren't currently wrapped as named methods on the client. Add wrappers as your consumer needs them — they're 3-line additions following the `add_memory` template.

---

## Key things to know

These are the gotchas that bite first-time integrators. Worth reading before you ship.

### `add_memory` is asynchronous

The HTTP call returns in under a second, but the entity extraction it triggers takes 2–10s typically. Your `search_nodes` calls won't find the new entities until extraction finishes.

If your consumer needs synchronous behavior (write-then-immediately-read), poll `search_nodes` with a 5–10s budget. The [smoke test](../scripts/smoke_brain.py) shows the pattern.

### `group_id` is the namespace boundary

Every call takes a `group_id`. All Phase 1 work uses `"brain"` as the single global namespace, which means cross-source entity dedup — your `Beatrice` from a captured note and your `Beatrice` from a Slack import collapse to the same node.

If you genuinely need isolation (test data, sandboxed-per-user later, etc.), use a different `group_id`. Smoke tests use `"smoketest"`. **Avoid `-` in group_ids** — RediSearch treats it as NOT and breaks the query silently. Stick to alphanumeric.

### Search is fuzzy by design

`search_nodes("Beatrice")` may return entities other than the literal "Beatrice" node — anything semantically close (people with similar names, the organization she works at, the project she's leading). That's a feature, not a bug, for most consumer use cases. If you need exact match, filter the results client-side or use `entity_types=[...]` to narrow.

### Errors and timeouts

The client raises on HTTP errors (non-2xx → `requests.exceptions.HTTPError`). MCP-level errors (the server returned a structured error inside a 200 response) raise `RuntimeError` with the error body. Timeouts are controlled by the `timeout` arg on `GraphitiClient.__init__` (60s default).

For consumer apps where the brain is an enhancement rather than a hard dep (like the Claude Code memory-injection hook), wrap the call in a try/except and degrade silently. The brain should never be a single point of failure for your app.

### Auth

- **Local dev:** no auth. `bearer=None`, talk to `http://127.0.0.1:8000`.
- **VPS:** bearer token at the Caddy layer. Set `BRAIN_BEARER_TOKEN` in your shell, pass it to the client, talk to `https://brain.{your-domain}`.

There is no per-consumer auth (no API keys, no rate limits, no per-app permissions). Anyone with the bearer can do anything. If you later need finer access control, that's a Caddy + Graphiti-MCP-server-extensions story we haven't built yet.

---

## TypeScript / other languages

We don't ship a typed TS client yet. The first external consumer scaffold will produce one (`BrainClient.ts`) and we'll point at it from here when it lands.

In the meantime, the wire protocol is simple enough to call directly from any HTTP-capable language. Here's the minimum TypeScript shape:

```typescript
// brain-client.ts — minimum-viable client. Use fetch (Node 20+).

type BrainOptions = { url: string; bearer?: string; groupId?: string };

export class BrainClient {
  private sessionId?: string;
  constructor(private opts: BrainOptions) {}

  async searchNodes(query: string, maxNodes = 10) {
    const result = await this.call("search_nodes", {
      query, group_ids: [this.opts.groupId ?? "brain"], max_nodes: maxNodes,
    });
    return result.nodes ?? [];
  }

  async addMemory(name: string, body: string, sourceDescription = "ts-client") {
    return this.call("add_memory", {
      name, episode_body: body,
      group_id: this.opts.groupId ?? "brain",
      source: "text", source_description: sourceDescription,
    });
  }

  private async call(toolName: string, args: any) {
    if (!this.sessionId) await this.initialize();
    const body = {
      jsonrpc: "2.0", id: crypto.randomUUID(),
      method: "tools/call", params: { name: toolName, arguments: args },
    };
    const r = await this.fetch(body);
    const msg = await this.parseResponse(r);
    if (msg.error) throw new Error(`MCP error: ${JSON.stringify(msg.error)}`);
    const text = msg.result?.content?.[0]?.text;
    return text ? JSON.parse(text) : msg.result;
  }

  private async initialize() {
    const body = {
      jsonrpc: "2.0", id: "init", method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "brain-ts-client", version: "0.1" },
      },
    };
    const r = await this.fetch(body);
    this.sessionId = r.headers.get("mcp-session-id") ?? undefined;
    if (!this.sessionId) throw new Error("no mcp-session-id returned");
    // Send the required notifications/initialized message:
    await this.fetch({ jsonrpc: "2.0", method: "notifications/initialized", params: {} });
  }

  private async fetch(body: any) {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
    };
    if (this.opts.bearer) headers["Authorization"] = `Bearer ${this.opts.bearer}`;
    if (this.sessionId) headers["Mcp-Session-Id"] = this.sessionId;
    return fetch(`${this.opts.url}/mcp`, {
      method: "POST", headers, body: JSON.stringify(body),
    });
  }

  private async parseResponse(r: Response) {
    const contentType = r.headers.get("content-type") ?? "";
    const text = await r.text();
    if (contentType.includes("text/event-stream")) {
      const last = text.split("\n").filter(l => l.startsWith("data:")).pop();
      return last ? JSON.parse(last.slice(5).trim()) : {};
    }
    return JSON.parse(text);
  }
}
```

That's enough to be productive in TypeScript today. Drop into your project, swap the URL for your brain endpoint, ship.

---

## How to test your integration

Before shipping a consumer, run it against an isolated graph so you don't pollute the real brain:

```python
brain = GraphitiClient(base_url="http://127.0.0.1:8000", group_id="my-consumer-test")
# ... do stuff ...

# Then wipe when you're done:
# python scripts/reset_brain.py --graph my-consumer-test --force
```

Or use the existing smoke as a template — `scripts/smoke_ingest.py` exercises ingest end-to-end against the dedicated `smoketest` graph and wipes on success.

If your consumer is non-trivial, write a smoke for it in its own repo following the same pattern: pick an alphanumeric `group_id`, write a few episodes, assert reads come back, wipe at the end.

---

## What's actually on the wire — and why you don't care

The brain currently speaks **MCP JSON-RPC over HTTP** as its wire protocol — the literal format of the bytes traveling between consumer and brain.

A raw call looks like this:

```http
POST /mcp HTTP/1.1
Content-Type: application/json
Accept: application/json, text/event-stream
Mcp-Session-Id: 7a8b9c-...

{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "tools/call",
  "params": {
    "name": "search_nodes",
    "arguments": { "query": "Beatrice", "group_ids": ["brain"] }
  }
}
```

Response comes back as a server-sent-events stream:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream

event: message
data: {"jsonrpc":"2.0","id":"req-1","result":{"content":[{"type":"text","text":"{\"nodes\":[...]}"}]}}
```

That whole framing — JSON-RPC envelope, `tools/call` method, session-id header, SSE response — is what "MCP wire protocol" means. It's *one specific way* of putting requests on the network. A REST wire protocol for the same intent would look completely different:

```http
POST /search HTTP/1.1
Content-Type: application/json

{"query": "Beatrice"}
```

Both wire protocols carry the same intent; they're just different framings.

**The reason you don't normally need to think about this:** `GraphitiClient` (Python) and the `BrainClient` recipe above (TypeScript) hide the wire protocol completely. Your consumer code calls `brain.search_nodes("...")`; the client constructs the JSON-RPC envelope, manages the session, parses the SSE response, returns Python/TypeScript objects. If we ever swap MCP for plain REST under the hood, only the client implementation changes — your consumer code stays identical.

That's the practical sense in which "MCP is just an implementation detail" — it's the bytes on the wire today, hidden behind a typed client.

---

## Why MCP underneath at all

Two reasons we use MCP as the wire protocol despite hiding it from consumers:

1. **Graphiti's MCP server speaks it natively.** We get the entire JSON-RPC + tool-discovery surface for free, including `search_nodes`, `search_memory_facts`, `add_memory`, `get_episodes`, and reranking tools. Building a REST wrapper would mean re-implementing them or proxying through. Pointless if the typed client is doing the typing job anyway.
2. **It's the right protocol for LLM-tool-discovery consumers.** Claude Code talks to MCP natively. Any future LLM-driven harness that wants generic brain access can register the brain as an MCP server and get the tool list. That's a *second* consumption pattern alongside the typed-client one — same server, two front doors.

So the architecture is:

```
                ┌─────────────────────────────────────────┐
Hard-coded ────▶│  GraphitiClient / BrainClient           │
consumer        │  (typed methods: search_nodes,          │
(Python/TS)     │   add_memory, search_memory_facts...)   │
                └────────────────┬────────────────────────┘
                                 │ wire protocol (MCP JSON-RPC today)
                                 │ — invisible to the consumer
LLM-driven ─────────────────────▶│
consumer                         │ raw MCP tool calls
(Claude Code,                    │ — discovered + invoked by the model
future agents)                   │
                                 ▼
                         Graphiti MCP server
                                 │
                                 ▼
                            FalkorDB
```

Same brain, two consumption patterns:
- **Typed-client (default).** Build new consumers against this. Hard-coded, IDE-completion-friendly, no runtime tool discovery.
- **MCP discovery (LLM harnesses only).** Register the brain as an MCP server in a Claude Code `.mcp.json` or similar. The LLM picks tools at runtime. We support this for Claude Code; see [`templates/claude-code-client/INSTALL.md`](../templates/claude-code-client/INSTALL.md).

The runtime-discovery pattern is powerful but explicitly *not* the default for consumer apps. It's harder to type, harder to test, and gives up determinism — see [`value-prop.md`](./value-prop.md) for why the typed-client path is the one to invest in.

---

## What changes if we swap protocols later

If we ever add a plain REST surface (likely candidate: a thin wrapper for shell-script consumers or very-simple integrations), the migration path is:

- **Typed clients** (`GraphitiClient`, `BrainClient`): change one internal method (`_call_tool` / `call`) to speak REST. Consumer apps unaffected. Method signatures unchanged.
- **MCP-discovery consumers** (Claude Code, future LLM harnesses): keep using MCP. The two surfaces coexist.

Nothing forces this swap right now. The MCP wire protocol works, and as long as the typed clients hide it, the cost to consumers is zero. We'd only add REST if a specific real consumer wanted one.

---

## Alternatives considered

- **MCP-discovery as the default integration pattern.** Rejected for non-LLM consumers — loses types, makes the surface ambiguous, depends on the consumer's LLM doing the right thing at runtime. Kept as the secondary pattern for LLM harnesses.
- **REST-only API.** Simpler wire, but we'd be re-implementing what Graphiti's MCP server already gives us, and we'd lose Claude-Code-style consumers without rebuilding the discovery surface anyway. Maybe later as additive.
- **gRPC.** Considered briefly. Better-typed than MCP wire-level, but adds protobuf to the brain build + every consumer build. Not worth it when typed clients give us the same DX over MCP.
- **A "brain agent" service in the middle (consumers ask natural-language questions, the service does query reformulation + synthesis).** Rejected — see [`value-prop.md`](./value-prop.md). Each consumer's synthesis needs differ; centralized smarts in the middle would be wrong for most of them. Per-consumer LLMs handle this naturally.
