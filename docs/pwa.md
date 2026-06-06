# brainbot PWA

One-screen mobile app. **Free-text capture is currently disabled:** with the
document-substrate cutover the brain's write path is source ingest (Notion pages
/ docs), not a `/capture` endpoint. The landing view is a small **dashboard** of
high-level facts about the brain (source + domain counts); the legacy
`POST /api/capture` still answers `410 Gone`. The backend is read-only against
the brain — it proxies `/api/recall` and `/api/map` (GET) so the dashboard,
search, and map views can read it, and never writes. The in-PWA "how the brain
works" docs and the evolution timeline also serve. The PWA holds no brain logic.

## Layout (under `pwa/`)

- `src/main.ts` — client logic (hash router; mounts the home dashboard, docs/evolution/search/map views)
- `src/home.ts` — home dashboard: source/domain facts read from `/api/map`
- `src/views.ts` — owner read-views: recall search (`#search`) and source map (`#map`)
- `src/style.css` — dark, mobile-first
- `src/server/index.ts` — Node HTTP server: serves `dist/`; read-only GET proxy for `/api/recall` and `/api/map`; `POST /api/capture` returns 410
- `public/manifest.webmanifest`, `public/sw.js` — PWA install bits

## Dev

```sh
cd pwa
npm install
# in one terminal: backend on :8787
npm run dev:server
# in another: vite dev on :5173 (proxies /api/* → :8787)
npm run dev:client
# or both at once:
npm run dev
```

Backend env:

```
PORT=8787
BRAIN_SERVICE_URL=http://localhost:8100   # where the backend reaches the brain
```

The dashboard, search, and map read the brain through the backend's `/api/*`
proxy, so it needs to know where the brain is. In prod (Docker) the brain is the
`brain` service on the shared network, so the default `http://brain:8100` works.
On the host that name doesn't resolve — point at the published port,
`http://localhost:8100`. **`npm run dev` (and `npm run dev:server`) set this for
you**; only override it if your brain is published elsewhere. Auth is not handled
here — it lives at the edge (oauth2-proxy in front of Caddy on the VPS). Local
`npm run dev` is unauthenticated.

## Smoke

1. `npm run dev`
2. Open http://localhost:5173
3. The home dashboard loads with high-level facts about the brain. With the brain running (and `BRAIN_SERVICE_URL` pointing at it) it shows real source/domain counts; otherwise a "couldn't reach the brain" note.
4. Visit `#search` / `#map` to read the brain, and `#docs` / `#learnings` for the in-PWA explainer and evolution timeline.

## Build & run (prod / Docker)

```sh
npm run build      # tsc server → dist-server/, vite client → dist/
npm start          # serves both on :8787
```

The `Dockerfile` does the same in a multi-stage build. Compose wires it into the brain network as the `pwa` service (see `compose/docker-compose.yml`).

## iOS install

Open the deployed URL in Safari → Share → Add to Home Screen. Launch from the icon → standalone window, no Safari chrome.

## Known gaps

- **Icons not committed.** `manifest.webmanifest` references `/icon-192.png` and `/icon-512.png`; drop real PNGs into `public/` before shipping the iOS install flow. The SW cache treats them as optional so dev works without them.
- **Google sign-in at the edge.** Caddy gates the PWA host (`brain.<domain>`) via `oauth2-proxy` (Google OIDC + email whitelist) — first launch bounces through Google once, then the session cookie persists. The whitelist is `compose/oauth2-proxy-emails.txt`. The app itself holds no auth code; local `npm run dev` is unauthenticated.
- **No offline capture queue.** Optimistic toast + retry covers flaky-network. Real offline lands later.
