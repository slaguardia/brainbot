# brainbot dashboard

The first-party web dashboard for the brain, and **the first app built on the [web-toolkit](./web-toolkit.md)**. It's a worked example of a platform app: a thin backend that proxies the brain read-only, plus a vanilla-TS frontend whose chrome, design tokens, and components all come from the toolkit (`@brainbot/web-toolkit`) — nothing is hand-mirrored here. It's a plain web app, not an installable PWA (no service worker or manifest) — the toolkit still ships those bits for apps that want them; this one just doesn't wire them up.

**Free-text capture is currently disabled:** with the document-substrate cutover the brain's write path is source ingest (Notion pages / docs), not a `/capture` endpoint. The legacy `POST /api/capture` still answers `410 Gone`.

The backend is read-only against the brain. It exposes a small `/api/*` of its own and **never writes to the brain** — the only writes it proxies are `POST /api/ingest` (the human pulling a Notion page in via discover) and `DELETE /api/sources/{id}` (revoking one back out). It keeps the brain's bearer token and URL server-side; the browser only ever talks to the backend.

The in-app "how the brain works" docs and the evolution timeline are **rendered from the canonical repo docs** (`docs/brain-architecture.md`, `docs/learnings.md`), bundled at build time via `?raw` imports and parsed with `marked`, so there is no hand-mirrored copy to keep in sync. The dashboard holds no brain logic.

## Views (hash router, from the toolkit shell)

The toolkit's `mountApp()` wires these routes (`dashboard/src/main.ts`):

- `#` (home) — the dashboard: source/domain counts, an inline **recall search** box, the **source map** (path tree), and the Notion **sync status** with a manual re-pull. Search and the map used to be separate routes; they now live on home.
- `#discover` — Notion discovery + selective ingest/revoke.
- `#integrations` — connect Notion (paste a token; a DB-stored token overrides the `NOTION_TOKEN` env) and set the **auto-sync interval** — how often the brain re-pulls changed Notion pages (`0` = off; overrides `BRAIN_POLL_INTERVAL_SECONDS`). Both take effect without a restart.
- `#apps` — the **launcher**: a card per app from the registry, each health-pinged (connected/offline) and linking out. See below.
- `#docs` / `#learnings` — the in-app explainer + evolution timeline, rendered from the repo docs (`chrome:false` full-bleed views).

## The #apps launcher

`src/apps.json` is a **hand-curated registry** — system config, **not** ingested into the brain (it isn't knowledge about you; it never enters `sources`/`chunks` — the two-kinds-of-data rule from [`app-platform.md`](./app-platform.md)). One entry per app: `{name, short_name, icon, url, health}`. `src/apps.ts` renders a card per entry, pings each `health` URL, and links out to `url`. Add an app by hand-editing `apps.json`.

## Layout (under `dashboard/`)

- `src/main.ts` — wires the brainbot views into the toolkit's hash router + nav.
- `src/home.ts` — home dashboard: counts + inline recall search + source map + Notion sync, via the toolkit's `recall()` / `map()`.
- `src/discover.ts` — Notion discovery + selective ingest/revoke view.
- `src/apps.ts` + `src/apps.json` — the launcher view and its registry.
- `src/docs.ts` — renders `docs/*.md?raw` for the `#docs` / `#learnings` views.
- `src/style.css` — app-specific CSS only (home/docs/discover); base + components come from the toolkit.
- `src/server/index.ts` — Node HTTP backend: serves `dist/`; `/api/me`, `/api/brain/{recall,doc,map}` (GET proxy, bearer server-side), `/api/notion/pages`, `POST /api/ingest`, `DELETE /api/sources/{id}`, `/api/health`; `POST /api/capture` → 410.
- `vite.config.ts` — extends the toolkit's Vite preset (dev `/api` proxy, `fs.allow ".."` for the `?raw` docs imports, dist build).

The dashboard depends on the toolkit as a local package (`"@brainbot/web-toolkit": "file:../web-toolkit"`); the Docker build context is widened to the repo root so it bundles the toolkit + repo docs.

## Dev

```sh
cd dashboard
npm install
npm run dev          # concurrently: client (vite :5173) + backend (:8787)
# or separately:
npm run dev:client   # vite on :5173 (proxies /api/* → :8787)
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
npm run build      # tsc server → dist-server/, vite client → dist/
npm start          # serves both on :8787
```

The `Dockerfile` does the same in a multi-stage build. Compose wires it into the brain network as the `dashboard` service (see `compose/docker-compose.yml`), behind the Caddy edge.

## Known gaps

- **Capture re-enable.** Free-text capture is disabled (the write path is source ingest). Real owner writes land with the source-editing surface.
- **Google sign-in at the edge.** Caddy gates the dashboard host (`brain.<domain>`) via `oauth2-proxy` (Google OIDC + email whitelist) — first launch bounces through Google once, then the session cookie persists. The whitelist is `compose/oauth2-proxy-emails.txt`. The app itself holds no auth code; local `npm run dev` is unauthenticated.
