# brainbot PWA

Phase 2 surface: one-screen mobile capture. Textarea + send button → `POST /api/capture`, which the thin Node server proxies to the brain service's `POST /capture` (decompose + ingest). The PWA holds no brain logic.

## Layout

- `src/main.ts` — client logic (textarea, button, optimistic toast, fetch)
- `src/style.css` — dark, mobile-first
- `src/server/index.ts` — Node HTTP server: serves `dist/` and proxies `POST /api/capture` → the brain service's `/capture`
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

Backend env (the server reads only these two; defaults work for local dev):

```
BRAIN_SERVICE_URL=http://127.0.0.1:8100   # the brain service's /capture endpoint
PORT=8787
```

Auth is not handled here — it lives at the edge (oauth2-proxy in front of Caddy on the VPS). Local `npm run dev` is unauthenticated.

## Smoke

1. `npm run dev`
2. Open http://localhost:5173
3. Type "PWA smoke check" → Send.
4. Toast appears in <100ms; the textarea clears.
5. Within a few seconds the episode shows up in FalkorDB Browser (http://127.0.0.1:3000, graph `brain`).

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
