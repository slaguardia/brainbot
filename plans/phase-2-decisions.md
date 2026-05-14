# Phase 2 — Design decisions log

Decisions made on the user's behalf while staging phase 2 scaffolding in their
absence. Every decision here is **reversible** — none have shipped to a deployed
environment. Push back on anything in this file when you return; the code can be
ripped out without affecting phase 1.

Companion to `plans/phase-2-pwa-harness.md`. Where this file and the plan
disagree, this file wins (it's newer).

---

## D1 — The "mind map" identity vs. the actual UI

**Question:** the project's brand is "mind map of my life." Should the literal
graph view be the home screen?

**Decision:** No. The graph is the *substrate*, not the *primary surface*. We
ship three views, with the graph viz as the third:

1. **Chat (`/`)** — primary surface, daily driver. Graph is invisible; tool
   calls surface as collapsed cards inline.
2. **Entity pages (`/entity/[id]`)** — a node + its 1-hop neighbors rendered as
   cards/lists. Card view, not a viz. This is what most "mind-map on a phone"
   use cases actually want.
3. **Explore (`/explore`)** — force-directed graph viz, opt-in tab. Loads a
   subgraph rooted at a node or search query, never the whole graph. Cool on
   desktop, viable on phone as "show me how X connects to Y."

**Why:** a literal force-directed hairball is a portfolio screenshot, not a
daily-use surface. Obsidian's graph view is gorgeous-but-unused for exactly
this reason. Entity pages cover the recall use case with mobile-friendly UI.

**Revisit if:** the user says they want the graph viz as the home screen.
Reverting is a single-line route swap.

---

## D2 — Graph viz library

**Decision:** `react-force-graph` (well, the Svelte equivalent — `d3-force` +
hand-rolled, OR `cytoscape` if we want richer layouts). Lock in at the moment
we actually need the Explore tab; for now the scaffolding leaves
`src/routes/explore/` as a placeholder.

**Why:** Obsidian-aesthetic, ~1k node ceiling is fine for a personal graph,
d3-force underneath is well-understood.

**Backend integration:** never load the whole graph. Add
`/api/graph/neighborhood?node=X&depth=2&limit=50` that runs a Cypher query
directly against FalkorDB and returns `{nodes, edges}`. The viz never knows
Graphiti exists.

---

## D2.5 — Graphiti transport: MCP JSON-RPC, not REST

**Question:** how does Phase 2's `pwa/src/lib/server/graphiti.ts` talk to
Graphiti?

**Original scaffold (wrong):** REST calls to `/search/hybrid`,
`/search/nodes`, `/nodes/{uuid}`, `/episodes`.

**Decision:** **MCP JSON-RPC over `/mcp/`**, matching the Phase 1 migrator
(`migrate/graphiti_clients.py`) and the Claude Code hook
(`templates/claude-code-client/inject_memory.py`).

**Why:** Phase 1 ships `zepai/graphiti-mcp:latest`, which is the MCP-only
image — it does not serve a REST surface. The REST endpoints I originally
wrote into `graphiti.ts` would have 404'd against Phase 1's stack. The
alternative was to ask Phase 1 to swap to `zepai/graphiti` (the core image,
which serves REST), but the migrator and hook already use MCP — adding a
second transport would create drift.

**Tool name mapping (verified against upstream):**
| Phase 2 function | MCP tool |
|---|---|
| `searchNodes()` | `search_memory_nodes` |
| `searchFacts()` | `search_memory_facts` |
| `addMemory()` | `add_memory` |
| `getEntity()` | composite: `search_memory_nodes` + `search_memory_facts` |

Single global `group_id = "brain"` for cross-source dedup, matching Phase 1's
convention.

**Revisit if:** Phase 1 swaps to the core image (`zepai/graphiti`). Then we
*can* use REST and the simpler request shapes, though the migration is
forward-only (REST returns slightly different node/edge shapes than MCP).

---

## D3 — Framework

**Decision:** **SvelteKit** (already defaulted in the plan). Adapter-node so
the same process serves UI and API. No external auth library (custom bearer +
signed cookie). No CSS framework — hand-rolled design tokens in a single
`app.css` file.

**Why no Tailwind:** "feels like Claude" is a specific aesthetic best achieved
with hand-crafted spacing + type, not utility classes. Can be added later if
the codebase outgrows hand-rolled CSS.

**Revisit if:** the component count gets past ~30 and CSS variables start to
sprawl. Tailwind is a 1-day migration.

---

## D4 — Conversation storage

**Decision:** **Postgres** in `brain.conversations` + `brain.messages` tables,
not IndexedDB.

**Why:** cross-device sync is the actual reason this project exists ("draft
on the train, see it on the laptop"). IndexedDB-only loses that. We already
have Postgres on the box.

**Cost:** writes on every message. Negligible.

---

## D5 — Home screen: chat-first vs. workflow-first

**Decision:** **chat-first.** `/` is the open chat. `/draft` is reachable via
a quick-action tile in the composer area.

**Why:** open chat is the more flexible primitive. A user who knows what they
want can type "draft outreach to Acme" and the LLM routes to the right tool.
A workflow form locks the user into one path.

**Revisit if:** real-world use shows people always want the form. Cheap to
swap — both routes exist.

---

## D6 — Voice-to-text tiers

| Tier | What | Phase | Notes |
|---|---|---|---|
| 0 | iOS keyboard dictation via real `<textarea>` | **Phase 2** | Free, works today, requires no code beyond using a textarea |
| 1 | Web Speech API mic button | **Skip** | Inconsistent across browsers; UX never feels native |
| 2 | MediaRecorder → `/api/transcribe` → Groq Whisper-large-v3 | **Phase 2.x** | Stub the endpoint now, wire when phase 2 is solid |

**Decision:** Phase 2 ships with Tier 0 only. The composer is a polished
`<textarea>` so iOS dictation "just works." A `/api/transcribe` route stub
exists now so Tier 2 has a place to land later.

**Why Groq for Tier 2:** Anthropic does not offer transcription. Groq's hosted
Whisper-large-v3 is fast (~300ms) and cheap (~$0.0001/sec). OpenAI Whisper is
the fallback.

---

## D7 — Visual identity

**Decision:** **Claude-aesthetic neutral warm** as a starting palette, with a
single accent color that is **not** Claude's coral (to avoid trademark
collision and let the project have its own identity). Tokens live in
`pwa/src/app.css`:

- Background: warm off-white `#FAF9F7` (light) / `#1A1A1A` (dark)
- Text: `#1F1F1F` / `#E8E8E8`
- Accent: `#5B6CFF` (a desaturated indigo — distinct from Claude's coral)
- Border: low-contrast hairlines, `#E5E2DC` / `#2E2E2E`
- Radius: 12 (cards), 8 (buttons), 24 (composer)
- Type: system-ui stack, generous line-height

**Revisit:** the accent color is a placeholder. Easy to change in one variable.

---

## D8 — Accessibility floor (non-negotiable)

- WCAG AA contrast both themes
- Semantic HTML — `<main>`, `<nav>`, `<button>` not `<div onclick>`
- Focus rings visible and brand-colored
- ARIA labels on streaming state and tool-call cards
- Touch targets ≥44pt
- Respect `prefers-reduced-motion`
- Keyboard shortcuts on desktop: Cmd+K (new chat), Cmd+/ (focus composer)
- VoiceOver/TalkBack tested before phase 2 portfolio shot

---

## D9 — What's safe to scaffold now vs. blocked on phase 1

**Scaffolded and verified (works without phase 1):**
- PWA project structure, manifest, service worker
- UI shell — chat page, composer, message bubble, tool-call card,
  conversation drawer
- Theme tokens, layout, navigation
- SQL migration files + idempotent runner
- Tool definition skeletons (handlers return brain_offline cleanly)
- Instrument wrapper, pricing table
- Dockerfile + compose snippet + Caddyfile snippet (additive)
- **Conversation persistence** — `/api/conversations`, `/api/conversations/[id]`,
  chat endpoint writes user + assistant messages to `brain.messages`,
  drawer renders the list, auto-titles on first user message
- **PWA icons** — 192/512/maskable PNGs generated from `favicon.svg`,
  `npm run icons` regenerates
- **Background worker** for `brain.pending_episodes` — boots once on
  first request via `hooks.server.ts`, claims rows with `SKIP LOCKED`,
  retries up to 5× then marks failed
- **Auth (cookie + bearer)** — `/login?token=…` issues a signed
  `__Host-session` cookie for 30 days; both header and cookie paths verified
  end-to-end with 401/303/200 responses

**Blocked on phase 1 (stubs only — return brain_offline cleanly):**
- Anything that calls Graphiti MCP (search-brain, recall-outreach,
  get-company, add-episode, draft-outreach) — code is correct, just has
  no server to talk to
- `/api/graph/neighborhood` (needs FalkorDB available)
- `/admin` cost data (needs real tool calls flowing)

**Blocked on phase 1.5:**
- Live deployment behind Caddy at `app.{domain}`

---

## D10 — What's deferred (don't build yet)

- Voice Tier 2 (defer until phase 2 chat is solid)
- Graph viz (defer until phase 1 migration has populated the graph; can't tune
  layouts without representative data)
- iOS Shortcuts capture endpoint (phase 3)
- Schema migrations tool (`node-pg-migrate`) — bare SQL files are fine until
  there are >5 migrations
- Authentication beyond bearer-in-header (cookie path is in the plan; defer
  until first real device test)

---

## Open questions still requiring user input

1. **Accent color.** `#5B6CFF` is my best guess. If you have a brand color
   preference, set `--color-accent` in `pwa/src/app.css`.
2. **Project name in the manifest.** Currently "Brainbot." Change in
   `pwa/static/manifest.webmanifest` if you have a different public name.
3. **App domain.** Currently `app.{domain}` in the Caddyfile snippet. Set
   `APP_DOMAIN` env var.
4. **Bearer token strategy.** Header for API, cookie after `/login` for
   browsing — implementation deferred until first device test.
