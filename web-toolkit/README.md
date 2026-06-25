# @brainbot/web-toolkit

The shared frontend package every brain-backed app's PWA is built from (platform
layer **L3**). Vanilla TS + Vite, **no UI framework, no third-party component
library, zero runtime UI deps.** It gives every app the same skin, app shell,
offline plumbing, sign-in handling, and brain access — so an app author writes
only app-specific views and `/api/*` routes.

See [`docs/web-toolkit.md`](../docs/web-toolkit.md) (the spec) and
[`docs/app-platform.md`](../docs/app-platform.md) (the why) for the design.

> **Seeded in-repo for now.** This package lives at the brainbot repo root
> (matching how `docs/` were seeded). In production it becomes **its own repo**
> consumed as a **git-tag dependency** (e.g.
> `"@brainbot/web-toolkit": "github:you/web-toolkit#v0.1.0"`). The in-repo
> consumer (the brainbot dashboard) depends on it via a `file:` path — see the
> recipe below.

## Modules (the public surface)

Each is a subpath export. JS modules point at the TypeScript **source** so an
in-repo Vite consumer transpiles them directly — there is **no build-order
coupling** (you do not have to build the toolkit before the app builds).

| Import | What it gives you |
|---|---|
| `@brainbot/web-toolkit/base.css` | the `:root` palette + base resets + shared app-chrome CSS. Import once. |
| `@brainbot/web-toolkit/components.css` | CSS for the component factories. Import if you use `components`. |
| `@brainbot/web-toolkit/tokens` | `tokens` (typed record of token names) + `cssVar()` |
| `@brainbot/web-toolkit/shell` | `mountApp(routes, opts)` hash router + `setLoading/setEmpty/setError` |
| `@brainbot/web-toolkit/components` | `button`, `card`, `table`, `modal`, `progress` + `streamInto` (SSE) |
| `@brainbot/web-toolkit/pwa` | `manifest(opts)` + `registerSW()` |
| `@brainbot/web-toolkit/pwa/sw.js` | the standard service worker (copy to your origin as `/sw.js`) |
| `@brainbot/web-toolkit/brain` | `recall(q,k?)`, `doc(id)`, `map()` — typed, via your `/api/brain/*` proxy |
| `@brainbot/web-toolkit/session` | `currentUser()` — reads `/api/me` |
| `@brainbot/web-toolkit/vite-preset` | `toolkitVite(opts)` base Vite config + `swSource` path |

### Theming rule

An app themes **only** via the CSS variables in `base.css` — never hard-coded
hex. The one per-app override allowed is the PWA manifest `theme_color` / icons
(app identity), not the palette.

---

## Scaffold contract — the exact recipe the dashboard follows

The **brainbot dashboard** is built on this toolkit. Because the toolkit is
in-repo, depend on it with a `file:` path.

### 1. Dependency line

In the brainbot dashboard's `dashboard/package.json`, add:

```jsonc
{
  "dependencies": {
    "@brainbot/web-toolkit": "file:../web-toolkit"
  }
}
```

Then `npm install` in `dashboard/`. (In production this line becomes a git-tag dep.)

### 2. Import specifiers

```ts
// dashboard/src/main.ts (the app entry)
import "@brainbot/web-toolkit/base.css";
import "@brainbot/web-toolkit/components.css";
import { mountApp } from "@brainbot/web-toolkit/shell";
import { HomeView } from "./views/home";
import { DocsView } from "./views/docs";
import { DiscoverView } from "./views/discover";

mountApp(
  {
    "": HomeView,            // catch-all home (no hash)
    docs: DocsView,          // matches #docs and #docs/<page> (longest-prefix)
    discover: DiscoverView,  // matches #discover
  },
  {
    title: "brain",
    nav: [{ label: "docs", href: "#docs", ariaLabel: "How the brain works" }],
  },
);
```

Each view is a factory `() => ({ mount(el) { ... } })`. Inside a view, use the
brain/session/component imports:

```ts
// dashboard/src/views/home.ts
import { recall, map } from "@brainbot/web-toolkit/brain";
import { currentUser } from "@brainbot/web-toolkit/session";
import { setLoading, setEmpty, setError } from "@brainbot/web-toolkit/shell";
import { button, card, table, progress, streamInto } from "@brainbot/web-toolkit/components";
import { tokens, cssVar } from "@brainbot/web-toolkit/tokens";

export const HomeView = () => ({
  async mount(el: HTMLElement) {
    setLoading(el, "Loading the brain…");
    try {
      const sources = await map();
      // …render with card()/table()/button()…
    } catch (e) {
      setError(el, String(e));
    }
  },
});
```

### 3. Vite config

```ts
// dashboard/vite.config.ts
import { defineConfig, mergeConfig } from "vite";
import { toolkitVite } from "@brainbot/web-toolkit/vite-preset";

export default mergeConfig(
  toolkitVite({ apiProxyTarget: "http://127.0.0.1:8787" }),
  defineConfig({
    // app-specific overrides only
  }),
);
```

### 4. Manifest + service worker (optional — only for an installable PWA)

*The brainbot dashboard skips this (it's a plain web app); scout uses it.*
Generate the manifest at build time and copy the SW into `public/` so Vite emits
`dist/sw.js` (a service worker only controls the scope it is served from):

```ts
// scripts/gen-pwa.ts  (run as a prebuild step)
import { writeFileSync, copyFileSync } from "node:fs";
import { manifest, /* */ } from "@brainbot/web-toolkit/pwa";
import { swSource } from "@brainbot/web-toolkit/vite-preset";

writeFileSync(
  "public/manifest.webmanifest",
  JSON.stringify(
    manifest({ name: "Brain", short_name: "Brain", description: "Two-second capture to the brain." }),
    null,
    2,
  ),
);
copyFileSync(swSource, "public/sw.js");
```

`registerSW()` (call it in your app entry) registers `/sw.js` in production and
self-heals (tears down stale SW + caches) on localhost.

### 5. Backend routes the app MUST expose

The `brain` and `session` clients call the app's OWN backend — never the brain
directly. The brainbot dashboard backend (`dashboard/src/server/index.ts`) must expose:

| Route | Proxies to | Returns (shape from `docs/consumer-api.md`) |
|---|---|---|
| `GET /api/brain/recall?q=&k=` | brain `GET /recall` | `{ chunks: Chunk[] }` |
| `GET /api/brain/doc?id=` | brain `GET /doc` | `Doc` (`{id,title,path,version,text}`) |
| `GET /api/brain/map` | brain `GET /map` | `{ sources: Source[] }` |
| `GET /api/me` | — (reads edge header) | `{ email }` or `{}` when none |

- The three `/api/brain/*` routes are the existing read-proxy pattern (the
  backend already proxies `/api/recall` and `/api/map`) re-pathed under
  `/api/brain/*` and forwarding the bearer + brain URL **server-side only**.
  The browser never sees a token or the brain origin.
- `/api/me` reads `X-Auth-Request-Email` off the incoming request (injected by
  the edge's oauth2-proxy) and echoes `{ email }`. With no edge in front (local
  dev) it returns no email and `currentUser()` resolves to `null` — no login UI.

That is the entire integration. Skin, shell, routing, SW, brain access, sign-in:
all inherited from the toolkit. The app author writes `views/*` and the four
backend routes above.

---

## Build & verify

```sh
npm install
npm run typecheck   # tsc --noEmit — proves the package type-checks
npm run build       # tsc -p tsconfig.build.json — emits dist/ JS + .d.ts (proves it compiles standalone)
```
