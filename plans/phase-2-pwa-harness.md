# Plan: Phase 2 — PWA: mobile capture surface

## Context

The project pivoted: the brain is a plug-and-play service for many apps, not a thing with a privileged UI. Most consumers will be headless (job-fit scorer, calendar prep, etc.) or live inside other tools (Claude Code MCP).

The PWA only earns its keep for the one job a mobile-installable web app does better than anything else: **capturing a thought in two seconds from a phone home-screen icon.** Everything else the original plan tried to bundle in is gone:

- **Chat** — dropped. If a conversational consumer is worth building, it's a separate app later. Not a Phase 2 problem.
- **Browse / Edit** — dropped. FalkorDB Browser at `127.0.0.1:3000` covers inspection. Direct entity editing is real product work and is deferred to Phase 3 quality-of-life.

What's left is small enough that the plan should be small too.

> **Update (build complete + architecture pivot).** Phase 2 shipped more than the PWA. While wiring capture we discovered graphiti's default extraction is hostile to abstract concepts (a personal brain's whole point), and that the graphiti **MCP server** — not graphiti-core — was hiding the levers to fix it. That led to a new **`brain/` service** (Python, FastAPI) that constructs graphiti-core directly and runs a decompose→extract pipeline. The PWA is now a thin proxy to that service rather than a direct graphiti consumer. See `brain/README.md` and the "Architecture as built" section below. The single-screen PWA scope is unchanged; what changed is what sits behind `/api/capture`.

**Definition of done:** Open PWA from phone home screen → type → tap send → see "captured" within 100ms → close. Episode lands in the brain (visible in FalkorDB Browser within a few seconds when extraction completes).

---

## Scope: one screen

- Textarea (auto-grow, autofocus on load).
- "Send to brain" button (or Enter).
- Optimistic ack: button click renders a "captured" toast in <100ms and clears the textarea immediately — does **not** wait for extraction.
- Posts `{ text }` to a small backend route that proxies to the **brain service** (`POST /capture`), which decomposes + ingests.
- Mobile-installable: manifest, icons, service worker shell. Installs to iOS home screen.

That's the whole feature.

---

## Architecture as built

```
phone PWA (single screen, optimistic ack)
   │  POST /api/capture { text }
   ▼
PWA backend  (TypeScript, thin proxy — pwa/src/server/)
   │  POST /capture { text }
   ▼
brain service  (Python + FastAPI — brain/)
   │  decompose (1 Claude call) → named-subject rewrite + N atomic facts
   │  graphiti-core add_episode × (1 + N), with custom_extraction_instructions
   ▼
graphiti-core (imported directly, NOT via MCP) → FalkorDB  (brain graph)

Claude Code consumer ──MCP──▶ graphiti MCP server ──▶ same FalkorDB
```

Why the brain service exists (vs. the PWA backend calling graphiti directly, as originally planned): the graphiti **MCP server** discards the controls a personal brain needs — `custom_extraction_instructions` (which took concept extraction from 2→20 entities), custom edge types, and the search recipes that fix domain-muddy retrieval. graphiti-core exposes all of it. So the brain calls graphiti-core directly and the MCP server is retained only for Claude Code, where MCP is the required integration contract. Full rationale in `brain/README.md` and the project memory note on the brain-service architecture.

---

## Stack

- **TypeScript.** Non-negotiable.
- **Vite + vanilla TS** (or Vite + a minimal framework if a UI primitive is needed). No SvelteKit, no Next.js — those were chosen for the chat + browse/edit surface area that no longer exists. One static page + one backend route doesn't justify a full meta-framework.
- **Backend:** a single Node handler (`pwa/src/server/`) that proxies `POST /api/capture` → the brain service's `POST /capture`. Thin: validates input, forwards, relays the result. All brain smarts live in the separate Python brain service (`brain/`), not here. (Original plan had this calling `add_memory` directly; see "Architecture as built" for why that changed.)

Revisit the framework choice only if mobile install + service-worker setup turns out to be enough work that a meta-framework's tooling actually pays for itself.

---

## Tasks

### 2.1 — Scaffold `pwa/`

New top-level `pwa/` directory. `npm create vite@latest pwa -- --template vanilla-ts`. Add:
- `public/manifest.json` — name, icons, theme color, `display: standalone`.
- `src/sw.ts` — minimal service worker (offline app shell; no background sync yet).
- `index.html` — one textarea, one button, one toast region.

**Verify:** `npm run dev` loads at `localhost:5173`; iOS Safari "Add to Home Screen" produces a standalone icon that launches the app.

### 2.2 — Capture route

Tiny Node handler at `POST /api/capture`. Body: `{ text: string }`. Action: call the brain's `add_memory` (HTTP or MCP — whichever client pattern Phase 1 settled on; reuse `migrate/graphiti_clients.py`'s shape in TS). Return `202 { episode_id }` as soon as the brain accepts the write; do not wait for extraction.

Env: `BRAIN_URL`, `BRAIN_BEARER_TOKEN`.

### 2.3 — Optimistic UX

On send:
1. Render toast "captured" immediately, clear textarea, return focus to it.
2. Fire-and-forget POST in the background.
3. If POST fails, replace toast with "send failed — retry" and restore the text. (Network failure is the only error worth handling here. Extraction errors are not visible at this surface — they'd show up in the brain's logs / FalkorDB browser.)

The whole point of the optimistic path is the <100ms ack on phone. Don't let any awaited work creep into the click handler.

### 2.4 — Deploy

Add a `pwa` service to `compose/docker-compose.yml`. Caddy route for `app.{$BRAIN_DOMAIN}`. Auth: Google sign-in + email whitelist enforced at the edge by an `oauth2-proxy` sidecar (Caddy `forward_auth`), not in the app. Full setup in [phase-2-pwa-auth.md](phase-2-pwa-auth.md). (The original bearer-at-the-edge approach was replaced once real per-identity auth + revocation was wanted; the brain API vhost keeps its bearer.)

---

## Explicitly out of scope (Phase 3 or later)

- Chat / agent harness. Becomes its own consumer app if/when there's a reason.
- Browse, search, or edit of brain contents. Use FalkorDB Browser.
- Entity rename / merge / delete UIs. Phase 3 quality-of-life.
- Offline capture queue with background sync. Add when actual offline use happens; until then the optimistic toast + retry covers flaky-network cases.
- Voice capture, image attachments, share-target intent. All real features, none of them Phase 2.

---

## Acceptance criteria

Each item is observable — pass/fail, no hand-waving. Items marked **(manual)** can only be verified on a real device or by eye; the rest can be checked from a terminal.

### Capture flow

1. **End-to-end write.** Type "ac smoke check" → tap Send → within 10s the episode is visible in FalkorDB Browser (`http://127.0.0.1:3000`, graph `brain`).
2. **Optimistic ack.** Toast renders and textarea clears **before** the `POST /api/capture` resolves. Verify by throttling DevTools network to "Slow 3G" — the UI must still feel instant. **(manual)** Target: toast visible within 100ms of click on a desktop browser; within 150ms on phone.
3. **Refocus.** After send, the textarea is empty and focused (caret blinking, virtual keyboard stays open on mobile).
4. **Failure path.** Stop the backend (`docker compose stop pwa`), tap Send → toast switches to "send failed — retry" in the error style, and the typed text is restored verbatim into the textarea. No silent drops.
5. **Empty / whitespace-only input is rejected.** Tapping Send with an empty or whitespace-only textarea is a no-op (no toast, no network call). The backend independently returns 400 for `{"text": ""}` or `{"text": "   "}`.

### Scope discipline

6. **One screen, nothing else.** No `/chat`, no `/browse`, no `/edit` routes. Direct navigation to any of those returns the index page (SPA fallback) — the visual audit confirms no chat UI, no entity browser, no settings page anywhere.
7. **No client-side state beyond the textarea.** Refresh = empty textarea, no history, no draft restoration. (Drafts are explicitly Phase 3.)

### Mobile / install

8. **iOS install.** Safari → Share → Add to Home Screen produces an icon that launches in standalone mode (no Safari chrome, status bar matches `theme_color`). **(manual)**
9. **Safe-area handling.** On a notched iPhone, the textarea and button respect top + bottom safe areas; nothing is hidden under the home indicator. **(manual)**
10. **Touch targets.** Send button is ≥44pt tall on phone — meets the iOS HIG minimum.

### Deployment / security

11. **Google auth at the edge.** `curl https://brain.<domain>/` → 302 into the oauth2-proxy/Google sign-in flow (not 200). A non-whitelisted Google account is denied by oauth2-proxy and never reaches the app; a whitelisted account reaches the index HTML and `POST /api/capture` → 202. (Auth is enforced by oauth2-proxy at the edge, not in the app — see [phase-2-pwa-auth.md](phase-2-pwa-auth.md). The brain API moved to `brain.api.<domain>`.)
12. **Network isolation.** The `pwa` container can reach `graphiti:8000` on the docker network but has no port exposed publicly; only Caddy is on the host's public interface. Verify with `docker compose ps` (no host port on the `pwa` line on VPS) and `docker exec pwa wget -qO- http://graphiti:8000/health` succeeding from inside.
13. **No secrets in the client bundle.** `grep -r BEARER dist/` returns nothing. The bearer never leaves the server side; the browser receives it only as a Caddy-edge concern.

### Observability

14. **Capture logs.** Each capture writes one start line and one done line to stderr in the documented shape: `[capture] start name=... chars=N` / `[capture] done ms=... status=ok|err`. `docker logs pwa` is the entire dashboard.

---

## Portfolio artifact

10-second screen recording: phone home screen → tap icon → type a thought → tap send → toast → close. Caption: "Two seconds from thought to brain." That's the entire pitch.

---

## Risks

- **The optimistic ack hides extraction failures.** That's the trade. The brain's logs are the place to notice extraction problems; this surface isn't trying to.
- **Service worker + iOS standalone has rough edges.** Budget half a day for the install-flow polish (icons at the right sizes, theme color, status bar). Skipping this is what makes a PWA feel like a hack instead of an app.
- **~~Bearer-in-header on phone is annoying.~~** Resolved: the PWA now uses Google sign-in + email whitelist at the edge (oauth2-proxy), so there's no bearer to carry on the phone — a session cookie persists after the first Google login. See [phase-2-pwa-auth.md](phase-2-pwa-auth.md).
