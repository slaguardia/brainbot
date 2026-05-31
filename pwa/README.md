# brainbot PWA

One-screen mobile app. **Free-text capture is currently disabled:** with the
document-substrate cutover the brain's write path is source ingest (Notion pages
/ docs), not a `/capture` endpoint. The send button is disabled and shows a short
note; the backend serves static assets only and answers the legacy
`POST /api/capture` with `410 Gone` (no broken proxy, no console error). The
in-PWA "how the brain works" docs and the evolution timeline still serve. The
PWA holds no brain logic.

## Layout

- `src/main.ts` — client logic (hash router for the docs/evolution views; capture send is disabled)
- `src/style.css` — dark, mobile-first
- `src/server/index.ts` — Node HTTP server: serves `dist/`; the `/api/capture` proxy is disabled (returns 410)
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

Backend env (defaults work for local dev):

```
PORT=8787
```

(With capture disabled the server no longer talks to the brain, so there's no
`BRAIN_SERVICE_URL`.) Auth is not handled here — it lives at the edge
(oauth2-proxy in front of Caddy on the VPS). Local `npm run dev` is
unauthenticated.

## Smoke

1. `npm run dev`
2. Open http://localhost:5173
3. The capture screen loads with a disabled send button and a short "capture paused" note — no request fires, no console error.
4. Visit `#docs` and `#learnings` — the in-PWA explainer and evolution timeline render.

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
