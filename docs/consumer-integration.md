# Consumer integration guide

How your app talks to the brain. Read top to bottom if you've never used the brain; otherwise skip to the section you need. The exhaustive per-operation spec lives in [`consumer-api.md`](./consumer-api.md) — this is the tutorial.

The brain exposes **three operations** — `capture`, `recall`, `profile` — over two front doors:

- **Plain HTTP/JSON** (`POST /capture`, `GET /recall`, `GET /profile`). **This is the path for typed consumers.** No session handshake, no protocol library — just HTTP.
- **MCP** at `/mcp` — the same three operations as tools, for Claude Code and other LLM-tool-discovery harnesses. See [`templates/claude-code-client/INSTALL.md`](../templates/claude-code-client/INSTALL.md).

Build normal apps against the HTTP face. Reserve MCP for LLM harnesses that discover tools at runtime.

---

## Quickstart — your first brain call in 5 minutes

With a brain running locally (see the [README](../README.md) "Running it"), this gets you a working call.

**1. Install the dep.** The reference client uses `requests`:
```sh
pip install requests
```

**2. Copy or import the client.** It lives at `migrate/graphiti_clients.py` (~80 lines, stdlib + requests; the filename is historical). Copy it into a sibling project, or import it in-repo.

**3. Make your first call:**
```python
from graphiti_clients import BrainClient

brain = BrainClient(
    base_url="http://127.0.0.1:8100",   # local; https://brain.api.{domain} on the VPS
    bearer=None,                          # set to BRAIN_BEARER_TOKEN on the VPS
)

# Write: capture a thought (decompose + extract happens server-side)
print(brain.capture("Talked to Beatrice about migrating off Kafka."))
# → {"mode": "decomposed", "episodes": 4, "topic": "...", "facts": 3}

# Read: ask a question
for f in brain.recall("what is the user doing about Kafka", limit=8):
    print(round(f["score"], 2), f["fact"])
```

**4. Verify it worked.** `capture` returns once extraction finishes (seconds). Then `recall` should surface the facts, or look in the FalkorDB Browser at `http://127.0.0.1:3000` (graph dropdown → `brain` → `MATCH (n) RETURN n`).

---

## The three operations

Full schemas + exact return shapes are in [`consumer-api.md`](./consumer-api.md). Working knowledge:

### `capture(text) → dict`

Write content into the brain. The brain decomposes the text into atomic, named-subject facts and extracts each into the graph. Returns a small summary `{mode, episodes, topic, facts}`. **It awaits the full pipeline** (decompose + N extraction passes — seconds), so if your UX needs to feel instant, ack optimistically and call `capture` fire-and-forget (the PWA does this).

### `recall(query, limit=20) → list[dict]`

The workhorse read. Returns scored facts: `{fact, name, score, valid_at, invalid_at}`, best-scored first. **`score` is an absolute on-target cosine — the brain reports it but does not threshold.** Your consumer decides what's strong enough; uniformly low scores mean the brain doesn't really know the answer. Each `fact` carries its own domain context (the graph is hub-shaped), so you usually don't need to traverse.

### `profile() → list[dict]`

Every currently-true fact about the user, unscored, newest first. Use when you want the whole picture (let your consumer's LLM reason over all of it) rather than a targeted answer. Prefer `recall` for specific questions.

> **Note:** the old standalone Graphiti tool surface (`add_memory`, `search_nodes`, `search_memory_facts`, `get_episodes`, `delete_*`, `clear_graph`) is gone. The brain narrowed to capture/recall/profile. If you need raw graph introspection during development, use the FalkorDB Browser or `scripts/reset_brain.py`, not a consumer call.

---

## Key things to know

These bite first-time integrators.

### `capture` is slow (and that's by design)

The HTTP call doesn't return until decompose + extraction finish — typically a few seconds. Don't block a user-facing interaction on it; ack first, capture in the background. For batch ingest, expect per-item latency and run sequentially.

### Recall is scored, not filtered

`recall` always returns its best candidates with a `score`. There's no server-side relevance cutoff. Gate on `score` in your consumer (a simple floor, or feed all of them to an LLM and let it judge). This is deliberate — different consumers want different precision/recall trade-offs.

### `group_id` / namespace

All work uses the single `brain` namespace (the brain sets it via `BRAIN_GROUP_ID`), so entities dedupe across sources — your `Beatrice` from a captured note and from a Slack import collapse to one node. Isolation (test sandboxes) is handled operationally with a separate graph; smokes use `smoketest`. **Avoid `-` in graph names** — RediSearch treats it as NOT.

### Errors and timeouts

The reference client raises `RuntimeError` on non-2xx responses. For consumers where the brain is an enhancement rather than a hard dependency (like the Claude Code injection hook), wrap the call in try/except and degrade silently — the brain should never be a single point of failure for your app. `capture`'s multi-second latency means you want a generous timeout (60s default).

### Auth

- **Local dev:** no auth. `bearer=None`, talk to `http://127.0.0.1:8100`.
- **VPS:** bearer at the Caddy layer on the **API host**. Set `BRAIN_BEARER_TOKEN`, pass it to the client, talk to `https://brain.api.{your-domain}`. (The bare `brain.{domain}` host is the human PWA, gated by Google sign-in — not for programmatic consumers.)

There's no per-consumer auth (no API keys, no rate limits, no per-app permissions) — one bearer, full access. Finer control would be added at the Caddy layer if it's ever needed.

---

## TypeScript / other languages

No shipped TS client yet, but the HTTP contract is trivial — plain JSON, no MCP. Minimum shape (Node 20+):

```typescript
// brain-client.ts — minimum-viable HTTP client.
type BrainOptions = { url: string; bearer?: string };

export class BrainClient {
  constructor(private opts: BrainOptions) {}

  private headers() {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.opts.bearer) h["Authorization"] = `Bearer ${this.opts.bearer}`;
    return h;
  }

  async capture(text: string) {
    const r = await fetch(`${this.opts.url}/capture`, {
      method: "POST", headers: this.headers(), body: JSON.stringify({ text }),
    });
    if (!r.ok) throw new Error(`capture failed: HTTP ${r.status}`);
    return r.json(); // { mode, episodes, topic, facts }
  }

  async recall(query: string, limit = 20) {
    const u = new URL(`${this.opts.url}/recall`);
    u.searchParams.set("q", query);
    u.searchParams.set("limit", String(limit));
    const r = await fetch(u, { headers: this.headers() });
    if (!r.ok) throw new Error(`recall failed: HTTP ${r.status}`);
    return (await r.json()).facts as Array<{ fact: string; name: string; score: number }>;
  }

  async profile() {
    const r = await fetch(`${this.opts.url}/profile`, { headers: this.headers() });
    if (!r.ok) throw new Error(`profile failed: HTTP ${r.status}`);
    return (await r.json()).facts;
  }
}
```

That's enough to be productive. Swap the URL for your brain endpoint and ship.

---

## How to test your integration

Run against an isolated graph so you don't pollute the real brain. `capture`/`recall`/`profile` take an optional `group_id` (defaults to the brain's configured namespace), so isolation is just a different graph name — no separate brain:

```sh
BRAIN_URL=http://127.0.0.1:8100 python scripts/smoke_ingest.py   # ingest → recall, end-to-end
# smoke_ingest.py drops the smoketest graph on success; or wipe manually:
python scripts/reset_brain.py --graph smoketest
```

For a non-trivial consumer, write a smoke in its own repo: `capture(..., group_id="my-test")` a few known facts, assert `recall(..., group_id="my-test")` returns them, then `reset_brain.py --graph my-test` at the end.

---

## What's actually on the wire — two front doors

The brain serves both faces from one process (`brain/api.py`):

```
                         ┌───────────────────────────────┐
Typed consumer  ─HTTP──▶ │  brain service (brain/api.py)  │
(Python/TS,              │   • POST /capture              │
 job scorer, hook)       │   • GET  /recall, /profile     │
                         │   • GET  /health               │
                         │                                │
LLM harness    ─MCP────▶ │   • /mcp tools:                │
(Claude Code)            │       capture, recall, profile │
                         └───────────────┬────────────────┘
                                         │ graphiti-core (in-process)
                                         ▼
                                    FalkorDB
```

- **Typed consumers use the HTTP routes.** Plain JSON, no session handshake. This is the default and the one to build against.
- **LLM harnesses use MCP.** Claude Code registers the brain as an MCP server (`/mcp`) and the model picks `capture`/`recall`/`profile` at runtime. The MCP session handshake (`initialize` → `mcp-session-id` header) is required for that face; see `templates/claude-code-client/INSTALL.md`.

Same brain, same three operations, two protocols. Earlier versions routed *all* consumers through MCP JSON-RPC (because the surface was the standalone Graphiti MCP server); now the brain owns the contract and offers plain HTTP as the front door for apps.

---

## Why MCP at all (since consumers use HTTP)

MCP is kept for one reason: **Claude Code and future LLM harnesses speak it natively.** Registering the brain as an MCP server gives the model runtime tool discovery (`capture`/`recall`/`profile`) with zero glue. That's a genuinely different consumption pattern from a typed app, and it's worth supporting — but it's *not* the default for ordinary consumers, which are better served by the typed HTTP client (IDE completion, easy testing, deterministic).

---

## What to read back: facts vs. episodes (important for every consumer)

The brain returns two kinds of thing, and **you must know which to trust for what**:

- **`facts`** (from `recall`) — structured `subject → relation → object` claims extracted into the graph. Precise, scored, deduped, bi-temporal. **But they are a lossy, positive-only index:** the extractor reliably captures what the user *does / wants / has* ("targets X", "uses Y") and **systematically drops negatives and rules** — "avoids Z", "only A or B counts", "anything outside this set is a hard skip". This is a property of graph extraction, not a bug we can fully tune away.

- **`episodes`** (from `profile`, and the `episodes` field of `recall`) — the faithful captured text. **Complete.** Contains the negatives, the gates, the rules — everything.

**The rule for consumers:**

> Use `facts` for fast, scored lookups of *positive* attributes. For anything **rule-bearing** — gates, avoid-lists, dealbreakers, conditional exceptions — read the **episode bodies** (`profile`, or `recall.episodes`). If you decide off `facts` alone, you *will* silently miss the user's hard "no"s.

Concretely: a job-fit consumer that reads only `facts` will see "targets these verticals" but miss "fintech is explicitly excluded" and "anything outside the set is an automatic skip" — and pursue something it should hard-skip. The negatives and the gate live only in the episode body. Pull the body.

Rule of thumb: **search with the facts; read the episode to be sure you have everything.** The episode body is the canonical record; the graph is an index over it.
