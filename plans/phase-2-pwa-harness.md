# Plan: Phase 2 — PWA + custom harness

## Context

Phase 1 made the brain queryable from Claude Code. Phase 2 builds the second surface: a Progressive Web App on phone + desktop, powered by a custom TypeScript agent harness on `@anthropic-ai/sdk`. This is where most non-coding usage happens — drafting outreach on the train, capturing thoughts, reviewing tracker state.

**The unlock vs. just using Claude Desktop / a generic chat UI:** custom tools tied to the brain. `draft_outreach`, `recall_similar_outreach`, `save_draft`, `add_episode` — these are domain-specific actions Steve's life needs, not generic LLM features.

**Two workstreams, mostly serial:**
1. PWA + harness scaffolding + first workflow ("Draft outreach")
2. `/admin` observability route — pulled forward from Phase 4 because it's a portfolio differentiator

**Definition of done for Phase 2:** Draft an outreach DM from phone on the train; the same draft is visible in Claude Code on the laptop 30 seconds later; `/admin` shows the tool calls that produced it with cost and latency.

---

## Pre-phase decision: framework

Default: **SvelteKit**. Lighter footprint, faster dev iteration, single Node process serves both UI and backend API.

Switch to **Next.js** only if: there's a specific component library or auth library you want that's Next-only.

This decision needs to land before Task 2.1.

---

## Workstream A — PWA + harness + first workflow

### Task 2.1 — Scaffold PWA project

**New directory:** `pwa/` (new top-level in brainbot repo)

```
npx sv create pwa --template minimal --types ts
cd pwa
npm i @anthropic-ai/sdk
```

Add:
- PWA manifest (`static/manifest.json`) — installable, name, icons, theme color
- Service worker (`src/service-worker.ts`) — offline shell only for now, no caching of API responses
- Base route `/` with a stub chat UI

**Verify:** `npm run dev` → loads on `http://localhost:5173` → "Add to home screen" works on iOS Safari.

### Task 2.2 — Backend skeleton: `/api/chat` streaming endpoint

**New file:** `pwa/src/routes/api/chat/+server.ts`

Behavior:
- Accepts `{ messages: AnthropicMessage[] }` POST body
- Holds the system prompt (writing-partner persona, voice rules summary, brain integration instructions)
- Calls `anthropic.messages.stream({ model: "claude-sonnet-4-6", tools: [...], messages })`
- Streams the response back as SSE

System prompt lives in `pwa/src/lib/server/system-prompt.ts` so it's editable without touching the route.

**Verify:** `curl -X POST localhost:5173/api/chat -d '{"messages":[{"role":"user","content":"hi"}]}'` streams a response.

### Task 2.3 — Tool: `search_brain`

**New file:** `pwa/src/lib/server/tools/search-brain.ts`

```ts
export const searchBrain = {
  name: "search_brain",
  description: "Search the personal knowledge graph for entities and facts...",
  input_schema: { /* { query: string, limit?: number } */ },
  handler: async (input) => {
    // POST http://graphiti:8000/search/hybrid with { query, limit: 5 }
    // returns combined node + edge results
  }
}
```

**Internal calls only** — `http://graphiti:8000` resolves on the docker network. No bearer token needed (the network is the boundary).

### Task 2.4 — Tool: `recall_similar_outreach`

**File:** `pwa/src/lib/server/tools/recall-outreach.ts`

Calls Graphiti `search_nodes` filtered to nodes typed as `Outreach`, ordered by vector similarity to the query. Returns the message body + outcome (responded? hired?).

### Task 2.5 — Tool: `get_company`

**File:** `pwa/src/lib/server/tools/get-company.ts`

Calls Graphiti `get_node` for a `Company` entity by name + traverses one hop to return all related people, applications, outreach, and notes.

### Task 2.6 — Tool: `add_episode` (fire-and-forget)

**File:** `pwa/src/lib/server/tools/add-episode.ts`

Critical: this MUST NOT block the response.

Pattern:
```ts
handler: async (input) => {
  // 1. Validate input synchronously
  // 2. Insert a "pending" row into brain.pending_episodes (Postgres)
  // 3. Return { status: "queued", episode_id: <pending row id> } immediately
  // 4. A background worker (separate Node process or in-process queue) drains
  //    pending_episodes by calling Graphiti add_episode, then marks them done
  //    or failed in Postgres
}
```

Reasoning: Graphiti extraction is 1–3s. If `add_episode` blocks the chat response, the UI freezes. Better: optimistic queue, surface failures via `/admin` or a toast next time the user opens the app.

### Task 2.7 — Tool: `draft_outreach`

**File:** `pwa/src/lib/server/tools/draft-outreach.ts`

Multi-step:
1. Calls `search_brain` for similar past outreach
2. Calls `get_company` for context on the target
3. Loads the voice rules (cached in memory at boot from a static load of voice-rule episodes)
4. Returns a structured draft `{ subject, body, channel, target_persona }` — the LLM uses this to compose the actual message in its response

This is a "compound tool" — the agent can call it once instead of orchestrating the three lookups itself.

### Task 2.8 — Tools: `save_draft` + `list_drafts`

**File:** `pwa/src/lib/server/tools/drafts.ts`

`save_draft`: writes to Postgres `brain.drafts` table (not Graphiti — drafts are app state, not memory). When a draft is *sent* (Steve marks it), then it gets converted to an `Outreach` episode in Graphiti.

`list_drafts`: queries `brain.drafts` for unsent drafts with optional filter by company.

**New table:**
```sql
CREATE TABLE brain.drafts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  target_persona TEXT,
  target_company TEXT,
  channel TEXT,
  subject TEXT,
  body TEXT NOT NULL,
  sent_at TIMESTAMPTZ,
  episode_id TEXT  -- set when promoted to Graphiti
);
```

### Task 2.9 — Chat UI: streaming markdown

**File:** `pwa/src/routes/+page.svelte`

- Textarea input (auto-grow), Send button (or Enter)
- Render assistant responses with streaming markdown (use `marked` + a code-highlighter)
- Show tool calls inline as collapsed cards: `🔧 search_brain("similar outreach to AI startup founders")` with results dropdown
- Mobile-first: respects safe-area insets, virtual keyboard handling

### Task 2.10 — Outreach workflow form

**File:** `pwa/src/routes/draft/+page.svelte`

A focused alternative to the open chat:
- Input: company URL OR LinkedIn URL OR plain company name
- Submit kicks off a chat-style flow with `draft_outreach` as the first tool call
- Inline-editable draft shown in a textarea
- "Save draft" button → calls `save_draft` tool
- "Mark as sent" button → promotes to Graphiti episode

This is the smoke-test workflow for Phase 2. If this end-to-end works on phone over the train wifi, the phase is real.

---

## Workstream B — `/admin` observability

This pulls forward Phase 4 work because it's a portfolio differentiator — most personal AI projects don't have observability and senior eng interviewers respect it.

### Task 2.11 — Postgres `brain.tool_calls` table

```sql
CREATE TABLE brain.tool_calls (
  id BIGSERIAL PRIMARY KEY,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  session_id UUID,                 -- groups tool calls within a single conversation
  tool_name TEXT NOT NULL,
  input_json JSONB NOT NULL,
  output_json JSONB,
  status TEXT NOT NULL,            -- 'success' | 'error' | 'timeout'
  latency_ms INT NOT NULL,
  model TEXT,                      -- which model was the parent chat using
  input_tokens INT,
  output_tokens INT,
  cost_usd NUMERIC(10, 6)
);

CREATE INDEX ON brain.tool_calls (occurred_at DESC);
CREATE INDEX ON brain.tool_calls (tool_name, occurred_at DESC);
```

### Task 2.12 — Tool-call instrumentation wrapper

**File:** `pwa/src/lib/server/tools/instrument.ts`

```ts
export function instrument<I, O>(tool: Tool<I, O>): Tool<I, O> {
  return {
    ...tool,
    handler: async (input) => {
      const start = Date.now();
      let status = "success", output, error;
      try { output = await tool.handler(input); }
      catch (e) { status = "error"; error = String(e); throw e; }
      finally {
        await db.insert(toolCalls, {
          tool_name: tool.name,
          input_json: input,
          output_json: output,
          status,
          latency_ms: Date.now() - start,
          // ... model, tokens, cost from outer chat context if available
        });
      }
      return output;
    }
  }
}
```

Wrap every tool registration with `instrument(...)`. One-line change per tool, complete coverage.

### Task 2.13 — `/admin` route

**New file:** `pwa/src/routes/admin/+page.svelte` + `pwa/src/routes/admin/+page.server.ts`

Server-side queries:
- Last 7 days: tool calls grouped by name, with count, p50, p99, error count
- Last 30 days: cost per day (sum of `cost_usd`), broken out by model
- Last 24h: latest 50 tool calls in a table (timestamp, tool, status, latency, cost)

Client renders:
- Top: current week summary cards (total calls, total cost, error rate)
- Middle: bar chart of cost per day (use `chart.js` or hand-rolled SVG — keep deps light)
- Bottom: recent activity table with input/output drill-down

Authn: same bearer-cookie as the rest of the app. No public access.

### Task 2.14 — Anthropic spend pricing table

**File:** `pwa/src/lib/server/pricing.ts`

Static map of `model → { input_per_mtok, output_per_mtok }`. Updated when new models drop. Used by the instrument wrapper to compute `cost_usd` for each tool call's parent chat turn.

---

## Deployment additions

### Task 2.15 — Add `pwa` service to docker-compose

**File:** `compose/docker-compose.yml`

```yaml
pwa:
  build: ../pwa
  environment:
    - DATABASE_URL=postgres://...@postgres:5432/personal
    - GRAPHITI_URL=http://graphiti:8000
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    - PWA_BEARER_TOKEN=${PWA_BEARER_TOKEN}
  depends_on:
    graphiti: { condition: service_healthy }
    postgres: { condition: service_healthy }
```

Internal port 3000, no public mapping. Caddy routes to it.

### Task 2.16 — Caddy route for `app.{domain}`

**File:** `compose/Caddyfile`

```
app.{$APP_DOMAIN} {
    @authorized header Authorization "Bearer {$PWA_BEARER_TOKEN}"
    handle @authorized {
        reverse_proxy pwa:3000
    }
    handle {
        respond 401
    }
}
```

Bearer-in-header is fine for API calls but inconvenient for browsing on phone. **Alternative:** signed cookie set after a one-time bearer authentication at `/login`. Cookie strategy details:
- After bearer match at `/login?token=...`, Caddy or the PWA sets `__Host-session=<signed>` for 30 days
- Subsequent requests use the cookie automatically
- Cookie revocable by rotating the signing key

Implement the cookie path; it's strictly better UX on phones.

---

## Phase 2 portfolio artifact

Landing page on personal website + Twitter thread.

**Landing page:** `website/brainbot.html` (or wherever the website lives)
- 30-second screen recording: open PWA on phone → draft outreach → switch to Claude Code on laptop → query "what did I just draft?" → see the draft
- Screenshot of `/admin` showing tool-call table with cost column populated
- Architecture diagram (already in `architecture.md`)
- "Read more" → links to `architecture.md` on GitHub

**Twitter thread:** "I built a personal AI agent over 2 weekends. Here's what mattered."
- Thread the architecture decision (graph vs vector) with the comparison table
- Show the `/admin` screenshot — observability is rare in personal projects, lean into it
- Demo video as the closer

**Discipline:** ship before starting Phase 3.

---

## Risks called out

- **Bearer-in-header on phone is annoying.** The cookie auth approach in 2.16 is non-trivial. Budget half a day for it; if it gets messy, fall back to bearer-in-URL for `/login` and accept the tradeoff for now.
- **Streaming + tool calls is fiddly.** The Anthropic SDK's streaming-with-tools pattern requires correctly buffering tool_use blocks across chunks. Reference: the SDK has a `stream` helper that handles this — use it, don't hand-roll.
- **Postgres schema drift.** Once `brain.drafts` and `brain.tool_calls` exist, schema changes need migrations. Use a lightweight migration tool (e.g. `node-pg-migrate`) from day one — adding it later means manually backfilling.
- **Cost-per-call attribution.** A single chat turn may make 5 tool calls. Attribution is "this whole turn cost $X, allocated proportionally" or "tool calls have no per-call cost; the parent chat does." Pick a convention up front and document it on the `/admin` route so the numbers make sense.
