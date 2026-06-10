# The web toolkit (L3) — spec

> The shared frontend package every app's PWA is built from. This is the
> **first-step gate** of the platform plan: you can't cleanly extract apps onto a
> common frontend without deciding the toolkit's public surface first. Companion
> to [`app-platform.md`](./app-platform.md) (the why) — this is the *what*.
> The toolkit lives at **`brainbot/web-toolkit/`** (a package inside the platform
> hub, not a standalone repo); apps consume it as a dependency. Written
> 2026-06-07.

## What it is

A small, **framework-free** (vanilla TS + Vite) package that gives every app's
PWA the same skin, shell, offline plumbing, sign-in handling, and brain access —
so an app author writes only app-specific views and `/api` calls. The donor is
brainbot's existing `pwa/` (already a working PWA); the toolkit is that,
generalized and extracted.

**Non-goal:** it is not a component framework, not a CSS utility library, not a
state-management library. It's the *platform-specific* glue (design tokens, app
shell, brain client, PWA bits) — app logic stays in the app.

## Design system is already reconciled — scout's palette wins

The reconciliation worry from `app-platform.md` is largely **already settled**.
brainbot's `pwa/src/style.css` opens with:

> *"Cool-dark palette ported from the scout consumer … The whole UI (chrome,
> buttons, docs, dashboard) speaks scout."*

So scout's design language is the canonical one, and brainbot already adopted it.
The toolkit's job is to **lift that `:root` token block into the shared package**
as the single source of truth, and have both apps consume it instead of each
holding a copy. The canonical tokens (from `pwa/src/style.css`):

```
Surfaces   --bg #0b0d12  --bg-2 #0f1218  --bg-elevated #14171f
           --panel-2 #181c26  --panel-3 #1d2230
Text       --fg #e8eaf0  --fg-muted #9099a8  --fg-faint #6c7484
Lines      --border #232838  --border-strong #2d3243
Brand      --accent #8b6dff  --accent-press #7a5cf0
Interactive--link #7aa9ff  --link-bg rgba(122,169,255,.12)
Semantic   --yes #34d399  --maybe #f5b942  --no #ef6464  (+ -bg variants)
Radius     --r-sm 4 --r-md 6 --r-lg 10 --r-xl 14
Motion     --ease cubic-bezier(.32,.72,0,1)  --dur-fast/base/slow 120/180/260ms
Shadows    --shadow-sm/md/lg
Fonts      --font-ui (system)  --font-mono (JetBrains Mono …)
```

These are the toolkit's contract for color/space/motion. An app must theme via
these variables, never hard-coded hex. The only per-app override allowed is the
PWA manifest `theme_color`/icon (app identity), not the palette.

## The public surface (what an app imports)

Six modules. An app depends on the package and uses these; everything else is
internal.

| Module | Exports | Replaces today's |
|---|---|---|
| **`tokens` / `base.css`** | the `:root` palette above + base resets (box-sizing, themed scrollbars, typography) | the duplicated `style.css` blocks in brainbot + scout |
| **`shell`** | the app chrome: header/nav, a hash-router mount (`mountApp(routes)`), and standard `loading` / `empty` / `error` states | brainbot `pwa/src/main.ts` hash router |
| **`components`** | the reusable UI elements — buttons, cards, tables, modals, the SSE progress view — **harvested from scout's existing UI**, not a third-party library | scout's `internal/web/index.html` elements |
| **`pwa`** | `manifest(opts)` generator (per-app name/short_name/icons/theme_color) + a standard `registerSW()` (offline app-shell + asset cache) | brainbot `pwa/public/manifest.webmanifest` + `sw.js` |
| **`brain`** | typed client: `recall(q, k?)`, `doc(id)`, `map()`, `changes(since?)`, `onChange(cb)` over the app backend's `/api` proxy; returns the brain's chunk/doc/map/change shapes from [`consumer-api.md`](./consumer-api.md) | brainbot `pwa/src/server` proxy + ad-hoc fetches |
| **`session`** | `currentUser()` — reads the identity the edge injects (`X-Auth-Request-Email`, surfaced by the app backend); no login UI, no token handling | nothing (no app does this yet) |

### Module contracts (sketch — finalize in the toolkit repo)

```ts
// shell
mountApp(routes: Record<string, () => View>, opts?: { title; nav?: NavItem[] }): void
//   hash-routes "#path" → view; renders header + nav; owns loading/empty/error.

// brain  (calls the *app's own* /api/brain/* proxy, never the brain directly —
//         the app backend forwards to the brain so the bearer/edge stay server-side)
recall(q: string, k?: number): Promise<Chunk[]>   // {id,heading,text,score,path}
doc(id: string): Promise<Doc>                       // {id,title,path,version,text} — verbatim
map(): Promise<Source[]>                            // {id,title,path,parent_id,version}
changes(since?: string): Promise<Change>            // {cursor,changed} — Tier 0 change signal
onChange(cb: () => void, opts?): () => void         // subscribe (polls changes); returns unsubscribe

// pwa
manifest(opts: { name; short_name; themeColor?; icons? }): WebManifest  // build-time
registerSW(): void                                  // runtime, in the app entry

// session
currentUser(): Promise<{ email: string } | null>    // from app's /api/me, fed by the edge header
```

### The brain-client boundary (important)

The toolkit's `brain` client talks to the **app's own backend** (`/api/brain/recall`
etc.), not to `brain.api.{domain}` directly. Reason: the bearer token and the
brain URL stay server-side in each app, exactly as brainbot's PWA already proxies
`/api/recall` and `/api/map`. The toolkit standardizes the *client* call; each app
backend keeps a tiny read-only proxy (`recall`/`doc`/`map`/`changes`). This preserves
[`consumer-integration.md`](./consumer-integration.md)'s read-only, no-secrets-in-
the-browser posture.

## Build preset

One shared `vite.config` base (TS strict, `?raw` markdown imports as brainbot
already uses for in-app docs, the SW build) that apps extend. Apps run the same
`vite build` → static `dist/` served by their backend. No per-app bundler config
to drift.

## How an app consumes it (scaffold contract)

```
my-app/
  backend/                 any language; serves /api/* JSON + /api/brain/* proxy + /api/me
  web/
    package.json           depends on web-toolkit (git tag dep to start)
    vite.config.ts         extends the toolkit preset
    src/
      main.ts              import { mountApp } from toolkit/shell
                           import { registerSW } from toolkit/pwa
                           mountApp({ '': HomeView, 'detail': DetailView })
      views/*.ts           app-specific views (use toolkit brain/session/shell)
    public/
      manifest.webmanifest generated via toolkit pwa.manifest({...})
      icon-192/512.png     app's own icons
```

The app author writes `views/*` and the backend's `/api/*`. Skin, shell, routing,
SW, brain access, sign-in: all inherited.

## Distribution

Git-tag dependency to start (zero infra — each app pins a toolkit tag). Move to a
private npm registry only when version churn across repos hurts. Cross-cutting
frontend changes are a toolkit bump per app — the accepted cost of the multi-repo
layout (see [`app-platform.md`](./app-platform.md)).

## Build order (matches the migration path)

1. **Extract** this package from brainbot's `pwa/`: lift the token block, the
   hash-router shell, the manifest+SW, and the proxy-client into `web-toolkit/`.
2. **Rebuild brainbot's PWA on it** — lowest risk (it's the donor), validates the
   toolkit against a real app before scout depends on it.
3. Scout's re-home (out of `go:embed`) then consumes the *validated* toolkit.

## Open decisions (settle in the toolkit repo)

- **Final module/export names** — the sketch above, firmed up against real usage.
- **Icon set** — brainbot's `manifest` still references uncommitted
  `icon-192/512.png` (see [`pwa.md`](./pwa.md) known gaps); the toolkit should
  ship a default + per-app override.
- **Offline depth** — v1 SW caches the app *shell* + assets only; per-app offline
  *data* is deferred until an app needs it.
- **Nav model** — whether the shell's nav is per-app config or pulls from the
  launcher registry (see `app-platform.md`).
