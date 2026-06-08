---
name: build-platform-app
description: Scaffold a new auxiliary app on the brain platform — a polyglot backend + a toolkit-built PWA behind the shared Caddy/SSO edge, reading the brain (recall/doc/map) and, where needed, fed by Notion via the brain's ingest. Use when the user wants to build/scaffold/plan a new app on the platform, a new brain consumer, or "another app like scout". Runs an interview → contract decision → .tasks checklist → scaffold flow.
---

# Build a platform app

A guided procedure for spinning up app N+1 on the brain platform. This skill is
the **how-to-build procedure**; the **architecture** lives in the brain's docs.
Point at those docs — never copy them here, so this can't go stale.

## Read first (canonical — source of truth)

In the brainbot repo:

- `docs/app-platform.md` — the 4-layer platform, the app contract, the
  "two kinds of data" rule, the edge, the launcher. **The governing doc.**
- `docs/web-toolkit.md` — the shared frontend package (tokens, shell,
  components, pwa, brain client, session) every app's PWA is built from.
- `docs/consumer-api.md` + `docs/consumer-integration.md` — the exact brain
  read contract (`recall` / `doc` / `map`) the app's brain client wraps.
- `docs/architecture.md` — the brain itself + the edge (Caddy + oauth2-proxy).

Read the relevant ones before planning. If they conflict with this skill, the
docs win.

## The contract (what every app must be)

> A **backend service** that owns its own domain data and talks to the brain
> read-only over HTTP, **+** a **PWA built from the shared web-toolkit**, **+**
> deployed behind the shared Caddy edge as one vhost.

The contract names no language — backends are **polyglot on purpose**.

## The flow

### 1. Interview

Ask only what you can't infer:

- **Purpose** — what does the app do, in one line? What's the core user action?
- **Knowledge source** — what does it need to know about the user? What of that
  already lives in Notion / the brain?
- **Data kind** (decides the store — see rule below): is the data it *produces*
  knowledge **about the user** (→ the brain) or this app's **working set**
  (→ its own store)?
- **Backend** — any reason to prefer a language (heavy batch → Go; embeddings →
  Python; thin CRUD → Node)? Default: smallest thing that fits.

### 2. Decide the contract

- **Data store (two-kinds rule, from app-platform.md):**
  - Working-set data → the app's **own store**, never inside the brain's dataset.
  - **SQLite** if the data is disposable + the app should stay a single
    run-anywhere binary (like scout).
  - A **dedicated database on the brain's Postgres *server*** only if the data is
    durable + concurrent. Same server, separate database — never the brain's
    schema.
- **Brain reads** — which `recall` queries / `doc` ids / `map` lookups it needs.
  The brain client calls the **app's own `/api/brain/*` proxy**, never
  `brain.api.{domain}` directly (keeps the bearer server-side).
- **Notion → brain** — if the app needs knowledge that isn't in the brain yet,
  that's a **prerequisite ingest**: the relevant Notion pages must be ingested
  as brain sources (`POST /ingest {url}`) before the app can recall them. Flag
  this explicitly; it's human-curated, not automatic.

### 3. Plan — emit an executable checklist

Write a `.tasks/FEAT-<timestamp>-<rand>/` task set in the app's repo, matching
the format already used by scout/brainbot (`feature.json` + `index.json` +
`stories/US-*.json`, acceptance-criteria-as-checklist, dependencies wired).
Standard stories for a new app:

1. Scaffold the backend (`/api/*` JSON + `/api/brain/*` read-only proxy +
   `/api/me`).
2. Build the PWA from the web-toolkit (its views + the app's `/api/*`).
3. Put it behind the shared edge (Caddy vhost + compose service).
4. Register it in the launcher app-registry.
5. (If needed) the Notion-ingest prerequisite.

### 4. Scaffold

- **Backend:** routes that serve JSON only (no HTML); a small read-only
  `/api/brain/*` proxy to the brain; `/api/me` exposing the edge's
  `X-Auth-Request-Email`.
- **Frontend:** `web/` depending on `@brainbot/web-toolkit` (it lives at
  `brainbot/web-toolkit/`; pin via a `file:` path like scout, or a git-tag dep),
  `vite.config`
  extending the toolkit preset, `manifest.webmanifest` via the toolkit's
  generator, the app's own icons.
- **Deploy:** a compose service on the internal network + a Caddy vhost
  `appname.{domain}` → forward_auth → the app (copy the template from
  app-platform.md's edge appendix).

### 5. Handoff

Give the user `/goal` prompts (one per phase) that read the `.tasks/` spec, work
stories in order honoring dependencies, delegate independent stories to parallel
subagents via the Task tool, and verify each story's acceptance criteria before
marking it done.

## Hard rules (non-negotiable — from the platform invariants)

1. **Two kinds of data.** App working set → the app's store; knowledge about the
   user → the brain. Never mix an app's tables into the brain's dataset. The
   brain is **read-only** for consumers.
2. **No third-party component library.** The toolkit's components are scout's
   existing elements, harvested. Reach for a library only for a single hard
   widget, per-component, never as the foundation.
3. **Vanilla TS + Vite for the PWA.** No React/Vue. One design system, one
   shell, one service worker — all from the toolkit.
4. **Backend renders no HTML** except serving the built PWA at `/`. Everything
   else is `/api/*` JSON.
5. **Auth lives at the edge.** The app contains no login code; it reads the
   injected identity header.
6. **Point at the docs, don't copy them.** This skill is procedure; the brain's
   docs are architecture.
