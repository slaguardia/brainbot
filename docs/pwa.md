# brainbot PWA

The first-party phone surface, and **the first app built on the [web-toolkit](./web-toolkit.md)**. It's a worked example of a platform app: a thin backend that proxies the brain read-only, plus a vanilla-TS PWA whose chrome, design tokens, service worker, and manifest all come from the toolkit (`@brainbot/web-toolkit`) — nothing is hand-mirrored here.

**Free-text capture is currently disabled:** with the document-substrate cutover the brain's write path is source ingest (Notion pages / docs), not a `/capture` endpoint. The legacy `POST /api/capture` still answers `410 Gone`.

The backend is read-only against the brain. It exposes a small `/api/*` of its own and **never writes to the brain** — the one write it proxies is `POST /api/ingest` (the human pulling a Notion page in via discover). It keeps the brain's bearer token and URL server-side; the browser only ever talks to the backend.

The in-PWA "how the brain works" docs and the evolution timeline are **rendered from the canonical repo docs** (`docs/brain-architecture.md`, `docs/learnings.md`), bundled at build time via `?raw` imports and parsed with `marked`, so there is no hand-mirrored copy to keep in sync. The PWA holds no brain logic.

## Views (hash router, from the toolkit shell)

The toolkit's `mountApp()` wires these routes (`pwa/src/main.ts`):

- `#` (home) — the dashboard: source/domain counts, an inline **recall search** box, the **source map** (path tree), and the Notion **sync status** with a manual re-pull. Search and the map used to be separate routes; they now live on home.
- `#discover` — Notion discovery + selective ingest.
- `#apps` — the **launcher**: a card per app from the registry, each health-pinged (connected/offline) and linking out. See below.
- `#docs` / `#learnings` — the in-app explainer + evolution timeline, rendered from the repo docs (`chrome:false` full-bleed views).

## The #apps launcher

`src/apps.json` is a **hand-curated registry** — system config, **not** ingested into the brain (it isn't knowledge about you; it never enters `sources`/`chunks` — the two-kinds-of-data rule from [`app-platform.md`](./app-platform.md)). One entry per app: `{name, short_name, icon, url, health}`. `src/apps.ts` renders a card per entry, pings each `health` URL, and links out to `url`. Add an app by hand-editing `apps.json`.

## Layout (under `pwa/`)

- `src/main.ts` — wires the brainbot views into the toolkit's hash router + nav; `registerSW()`.
- `src/home.ts` — home dashboard: counts + inline recall search + source map + Notion sync, via the toolkit's `recall()` / `map()`.
- `src/discover.ts` — Notion discovery + selective ingest view.
- `src/apps.ts` + `src/apps.json` — the launcher view and its registry.
- `src/docs.ts` — renders `docs/*.md?raw` for the `#docs` / `#learnings` views.
- `src/style.css` — app-specific CSS only (home/docs/discover); base + components come from the toolkit.
- `src/server/index.ts` — Node HTTP backend: serves `dist/`; `/api/me`, `/api/brain/{recall,doc,map}` (GET proxy, bearer server-side), `/api/notion/pages`, `POST /api/ingest`, `/api/health`; `POST /api/capture` → 410.
- `scripts/gen-pwa.ts` — prebuild: generates `public/manifest.webmanifest` from the toolkit and copies the toolkit's `sw.js` into `public/`. **Both are build artifacts (gitignored)** — the toolkit is the single source of truth for the manifest shape + the SW.
- `vite.config.ts` — extends the toolkit's Vite preset (dev `/api` proxy, `fs.allow ".."` for the `?raw` docs imports, dist build).

The PWA depends on the toolkit as a local package (`"@brainbot/web-toolkit": "file:../web-toolkit"`); the Docker build context is widened to the repo root so it bundles the toolkit + repo docs.

## Dev

```sh
cd pwa
npm install
npm run dev          # concurrently: client (gen-pwa → vite :5173) + backend (:8787)
# or separately:
npm run dev:client   # gen-pwa, then vite on :5173 (proxies /api/* → :8787)
npm run dev:server   # backend on :8787, BRAIN_SERVICE_URL preset to :8100
```

Backend env:

```
PORT=8787
BRAIN_SERVICE_URL=http://localhost:8100   # where the backend reaches the brain
```

The dashboard reads the brain through the backend's `/api/brain/*` proxy, so the backend needs to know where the brain is. In prod (Docker) the brain is the `brain` service on the shared network, so the default `http://brain:8100` works. On the host that name doesn't resolve — point at the published port, `http://localhost:8100`. **`npm run dev` (and `npm run dev:server`) set this for you**; only override it if your brain is published elsewhere. Auth is not handled here — it lives at the edge (oauth2-proxy in front of Caddy on the VPS), which injects `X-Auth-Request-Email` that `/api/me` reads. Local `npm run dev` is unauthenticated (no header → `/api/me` returns no identity).

## Smoke

1. `npm run dev`
2. Open http://localhost:5173
3. The home dashboard loads. With the brain running (and `BRAIN_SERVICE_URL` pointing at it) it shows real source/domain counts, search, and the map; otherwise a "couldn't reach the brain" note.
4. Visit `#discover`, `#apps`, and `#docs` / `#learnings`.

## Build & run (prod / Docker)

```sh
npm run build      # gen-pwa → tsc server → dist-server/, vite client → dist/
npm start          # serves both on :8787
```

The `Dockerfile` does the same in a multi-stage build. Compose wires it into the brain network as the `pwa` service (see `compose/docker-compose.yml`), behind the Caddy edge.

## iOS install

Open the deployed URL in Safari → Share → Add to Home Screen. Launch from the icon → standalone window, no Safari chrome.

## Known gaps

- **App icons not committed.** The generated `manifest.webmanifest` and the launcher registry reference per-app icons (`/icons/*.png`); drop real PNGs in before shipping the install flow. The SW cache treats them as optional so dev works without them.
- **Google sign-in at the edge.** Caddy gates the PWA host (`brain.<domain>`) via `oauth2-proxy` (Google OIDC + email whitelist) — first launch bounces through Google once, then the session cookie persists. The whitelist is `compose/oauth2-proxy-emails.txt`. The app itself holds no auth code; local `npm run dev` is unauthenticated.
- **No offline capture queue.** Capture is disabled; the offline shell is the toolkit's SW asset cache. Real offline write lands with the source-editing surface.
