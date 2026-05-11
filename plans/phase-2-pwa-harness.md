# Plan: Phase 2 — PWA: chat + browse/edit + capture

## Context

Phase 1 made the brain queryable from Claude Code. Phase 2 builds the second surface: a Progressive Web App on phone + desktop, powered by a custom TypeScript agent harness on `@anthropic-ai/sdk`. This is where most non-coding usage happens.

**The PWA has three modes, each a peer of the others, all reading and writing the same brain:**

1. **Chat** — conversational agent with tools over the brain
2. **Browse / Edit** — direct view and inline edit of episodes, entities, and relations
3. **Capture** — single-purpose append surface

**The unlock vs. just using a generic chat UI:** the human can directly read and edit brain data without going through the agent. When extraction gets something wrong, you fix it in the browser instead of writing a corrective episode and hoping. This is the strongest hedge against the bi-temporal-correction-only failure mode of graph-canonical systems.

**No second store in this phase.** The PWA backend talks to Graphiti and nothing else. Captures are synchronous (tap send, wait for extraction, see toast). Tool calls log to stderr. `/admin` and any persistent observability live in Phase 4 — their absence here is intentional simplicity, not an oversight.

**Two workstreams, mostly serial:**
1. PWA + chat harness scaffolding
2. Graph browser/editor — the surface that makes graph-canonical viable for daily use

(Capture is a single small route — folded into Workstream A as one task rather than its own workstream.)

**Definition of done for Phase 2 — the smoke test:** Capture a thought on phone → find it in the entity browser on laptop → edit it inline → ask the chat agent about it next turn → the answer reflects the edit. End to end in one session, exercising every surface against one source of truth.

---

## Pre-phase decision: framework

Default: **SvelteKit**. Lighter footprint, faster dev iteration, single Node process serves both UI and backend API.

Switch to **Next.js** only if there's a specific component library or auth library you want that's Next-only.

This decision needs to land before Task 2.1.

---

## Workstream A — PWA + chat harness + capture

### Task 2.1 — Scaffold PWA project

**New directory:** `pwa/` (new top-level in brainbot repo)

```
npx sv create pwa --template minimal --types ts
cd pwa
npm i @anthropic-ai/sdk
```

Add:
- PWA manifest (`static/manifest.json`) — installable, name, icons, theme color
- Service worker (`src/service-worker.ts`) — offline shell only for now
- Base routes: `/` (chat), `/browse` (graph), `/capture`

**Verify:** `npm run dev` → loads on `http://localhost:5173` → "Add to home screen" works on iOS Safari.

### Task 2.2 — Backend skeleton: `/api/chat` streaming endpoint

**New file:** `pwa/src/routes/api/chat/+server.ts`

Behavior:
- Accepts `{ messages: AnthropicMessage[] }` POST body
- Holds the system prompt (generic writing/thinking-partner persona; brain integration instructions)
- Calls `anthropic.messages.stream({ model: "claude-sonnet-<latest>", tools: [...], messages })`
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

### Task 2.4 — Tool: `get_entity`

**File:** `pwa/src/lib/server/tools/get-entity.ts`

Calls Graphiti `get_node` for an entity by id or name + traverses one hop to return all related entities, episodes, and edges. The agent uses this when a search hit needs more context.

### Task 2.5 — Tool: `add_episode`

**File:** `pwa/src/lib/server/tools/add-episode.ts`

Synchronous: validate input, POST to `graphiti add_episode`, return the resulting episode id. Extraction takes 1–3s; the chat tool call waits for it. The chat UI is already async-streaming, so this just shows up as a tool call that takes a few seconds.

If/when this latency becomes annoying (or when iOS Shortcut needs <100ms response in Phase 3), introduce an async queue. Not before.

### Task 2.6 — Tool-call logging

Every tool handler logs to stderr at start and end:
```
[tool] search_brain start input={"query":"..."}
[tool] search_brain done  ms=147 status=ok
```

This is the entire observability story for Phase 2. `docker logs pwa` is the dashboard. Real `/admin` UI lives in Phase 4 if/when log volume justifies it.

### Task 2.7 — Chat UI

**File:** `pwa/src/routes/+page.svelte`

- Textarea input (auto-grow), Send button (or Enter)
- Render assistant responses with streaming markdown (use `marked` + a code-highlighter)
- Show tool calls inline as collapsed cards: `🔧 search_brain("...")` with results dropdown
- Mobile-first: respects safe-area insets, virtual keyboard handling

### Task 2.8 — Capture API + screen

**Files:**
- `pwa/src/routes/api/capture/+server.ts` — `POST { text, source? }` → calls `graphiti add_episode` synchronously, returns 200 with the episode id when extraction completes
- `pwa/src/routes/capture/+page.svelte` — single-purpose view, big textarea, Send button, "captured" toast on response

The wait is real (1–3s). For the smoke test that's fine — the user is tapping send and watching for the toast. Phase 3 introduces an async path when the iOS Shortcut surface forces the issue.

---

## Workstream B — Graph browser / editor

This is the surface that makes graph-canonical viable. Without it, "the graph is the source of truth" means "the human has no direct lever." With it, the human can fix bad extractions, rename entities, prune wrong edges — the same way they'd correct a markdown file in the file-canonical alternative we parked.

### Task 2.9 — Read APIs for the browser

**New files:**
- `pwa/src/routes/api/graph/search/+server.ts` — `GET ?q=...` → hybrid search results (passes through to `search_brain` shape)
- `pwa/src/routes/api/graph/entity/[id]/+server.ts` — `GET` → entity attributes + one-hop neighbors + linked episodes
- `pwa/src/routes/api/graph/episode/[id]/+server.ts` — `GET` → full episode body + extracted entities + extraction status
- `pwa/src/routes/api/graph/recent/+server.ts` — `GET ?since=...` → chronological episode list (the "feed" view)

All read-only. All thin wrappers over Graphiti REST. No side effects.

### Task 2.10 — Mutation APIs for the editor

**New file:** `pwa/src/routes/api/graph/mutate/+server.ts`

Minimum mutation set:
- `update_episode_body(episode_id, new_body)` — re-extract is async; old extracted facts get invalidated bi-temporally
- `rename_entity(entity_id, new_name)` — propagates to all references
- `set_entity_attribute(entity_id, key, value)` — direct attribute edit
- `delete_entity(entity_id)` — soft delete (hides from search; the bi-temporal store keeps history)
- `delete_edge(edge_id)` — soft delete
- `merge_entities(keep_id, merge_id)` — moves all edges from `merge_id` to `keep_id`, soft-deletes `merge_id`

Each mutation logs to stderr (Task 2.6 pattern).

These six are the contract the browse/edit UI depends on. If Graphiti's REST doesn't expose all of them directly, the gap gets filled with thin server-side helpers that synthesize the operation from primitives.

### Task 2.11 — Browse/Edit UI

**Files:**
- `pwa/src/routes/browse/+page.svelte` — entry view: search box + recent-episodes feed
- `pwa/src/routes/browse/entity/[id]/+page.svelte` — entity detail card
- `pwa/src/routes/browse/episode/[id]/+page.svelte` — episode detail with body + extracted entities

**Entity detail card** shows:
- Name (inline-editable; rename calls `rename_entity`)
- Attributes (table; click to edit; save calls `set_entity_attribute`)
- Outgoing edges (each clickable to traverse; trash icon calls `delete_edge`)
- Incoming edges (same)
- Linked episodes (chronological; click to open episode detail)
- "Merge into another entity" action → modal with search-as-you-type → calls `merge_entities`

**Episode detail** shows:
- Body (textarea, inline-editable; save calls `update_episode_body`)
- Extracted entities (chips; click to navigate)
- Extraction status (pending/done/failed)

**Recent feed** shows chronological list of episode summaries, infinite-scroll, click to open. This is the "notes app" view — the closest the graph-canonical brain gets to "scroll through what I've captured lately."

The whole browser must work on phone. The merge-entities modal is the trickiest mobile UX; budget time for it.

---

## Deployment additions

### Task 2.12 — Add `pwa` service to docker-compose

**File:** `compose/docker-compose.yml`

```yaml
pwa:
  build: ../pwa
  environment:
    - GRAPHITI_URL=http://graphiti:8000
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    - PWA_BEARER_TOKEN=${PWA_BEARER_TOKEN}
  depends_on:
    graphiti: { condition: service_healthy }
```

Internal port 3000, no public mapping. Caddy routes to it. No volume — there's no persistent state to keep.

### Task 2.13 — Caddy route for `app.{domain}` + cookie auth

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

Bearer-in-header is fine for API but inconvenient on phone. Add a `/login?token=...` path that exchanges the bearer for a signed cookie (`__Host-session`, 30-day expiry, `Secure` + `HttpOnly`). Subsequent requests use the cookie. Cookie revocable by rotating the signing key.

Implement the cookie path. Strictly better UX on phones.

---

## Phase 2 portfolio artifact

Landing page on personal website + Twitter thread.

**Landing page:** 30-second screen recording of the smoke test:
- Phone: open PWA → Capture → type a thought → tap send
- Laptop: open PWA → Browse → search → click into the new entity
- Inline-edit a field → save
- Switch to Chat → ask about the captured thought → answer reflects the edit

**Twitter thread:** "I built a personal AI agent over 2 weekends. Three modes against one brain — here's what mattered."
- The architecture decision (graph vs vector) with the comparison table
- The browse/editor surface as the unlock — most personal AI projects are append-only chat; this one lets the human fix the brain directly
- Demo video as the closer

**Discipline:** ship before starting Phase 3.

---

## Risks called out

- **Bearer-in-header on phone is annoying.** The cookie auth approach in 2.13 is non-trivial. Budget half a day for it; if it gets messy, fall back to bearer-in-URL for `/login` and accept the tradeoff for now.
- **Streaming + tool calls is fiddly.** The Anthropic SDK's streaming-with-tools pattern requires correctly buffering tool_use blocks across chunks. Reference: the SDK has a `stream` helper that handles this — use it, don't hand-roll.
- **Synchronous captures will feel slow eventually.** 1–3s for extraction is fine for the smoke test, fine for typing on a laptop. On phone with a thought you're trying not to lose, it's borderline. When that becomes the active complaint, Phase 3's async-queue work is the answer.
- **Mutation APIs may need to be synthesized.** Graphiti's REST surface may not expose every mutation in the Task 2.10 list as a single call. Be prepared to compose them from primitives (e.g. `merge_entities` = enumerate edges + recreate on the keeper + soft-delete the merged node). If the synthesis gets gnarly, surface a known-limitation note in the relevant UI.
- **Mobile UX for the editor is real product work.** Inline-edit, merge modal, infinite-scroll feed — all need actual phone testing, not just responsive CSS. Plan for two test sessions on a real phone before shipping.
