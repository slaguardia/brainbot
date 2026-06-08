# Quickstart — run the brain locally

> The fast path to a working brain on your laptop: two containers, ingest a
> Notion page, recall it. For the production VPS deploy — provisioning the box,
> the Caddy/SSO edge, adding auxiliary apps, day-2 ops — follow
> [`deployment.md`](./deployment.md). This is the local/fresh-install path.

The stack is two compose services: `postgres` (pgvector) and `brain` (FastMCP +
asyncpg). Locally there's no Caddy, no TLS, and no `pwa` container — the brain
and Postgres bind to `127.0.0.1` and you run the dashboard host-native.

## 1. Configure env

```sh
cd compose
cp .env.example .env
```

Set in `compose/.env`:

- `VOYAGE_API_KEY` — embeddings (needs a card on file; see [`deployment.md` §0](./deployment.md#0-prerequisites-off-the-box)).
- `NOTION_TOKEN` — page fetch on ingest (the page must be shared with that integration).
- `POSTGRES_PASSWORD`.

(The VPS additionally needs `BRAIN_DOMAIN`, `BRAIN_BEARER_TOKEN`, and the Google
OAuth vars + `OAUTH2_PROXY_COOKIE_SECRET` — a [`deployment.md`](./deployment.md)
concern, not needed locally.)

## 2. Bring the stack up

No Caddy, no TLS; brain + postgres exposed on `127.0.0.1`; no `pwa` container.

```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
docker compose ps                       # both healthy?
```

The `brain` service is at `http://127.0.0.1:8100`; Postgres is inspectable at
`127.0.0.1:5432`. For the PWA locally, `cd pwa && npm run dev` (see
[`pwa.md`](./pwa.md)). Do **not** layer the local overlay on the VPS.

## 3. Smoke test

The live end-to-end smoke ingests a Notion page, then exercises `recall` /
`profile` / `map` and asserts the page's chunk comes back:

```sh
BRAIN_URL=http://127.0.0.1:8100 python scripts/smoke_substrate.py
```

It needs `NOTION_TOKEN` (the page must be shared with that integration) and the
brain running with `VOYAGE_API_KEY` + `PG_DSN`. See the script header for the
full env list and how to override the page.

## 4. Drop content in

The input is a Notion page. The brain fetches it, splits it into section chunks
(one per heading; an unheadinged page stays one chunk), embeds them, and serves
them back via `recall`:

```sh
curl -X POST http://127.0.0.1:8100/ingest \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.notion.so/Some-Page-<id>"}'
```

Re-ingesting the same page wipes-and-replaces its chunks, so the page stays the
source of truth. The PWA's discover view does the same thing from a phone, with
selective ingest.

## 5. Wire Claude Code (optional)

See [`../templates/claude-code-client/INSTALL.md`](../templates/claude-code-client/INSTALL.md)
for how to drop the MCP server entry and the `UserPromptSubmit` memory-injection
hook into any project repo — the canonical example of "a consumer talking to the
brain over HTTP/MCP."

## Setup gotchas

Two footguns bite local and VPS alike and are documented in the deployment
runbook: **Voyage needs a payment method on file** (without it you're throttled
to 3 RPM, which chokes ingest — [`deployment.md` §0](./deployment.md#0-prerequisites-off-the-box);
swap the embedder via `BRAIN_EMBED_MODEL` + `EMBED_DIM` if you'd rather not use
it, see [`embedder.md`](./embedder.md)), and **`.env` loads only from
`compose/.env` and won't reload on `docker compose restart`** — edit it, then
`down && up` ([`deployment.md` §3](./deployment.md#3-get-the-code--configure-env)).

Local-specific:

- **The MCP endpoint is `/mcp`** (no trailing slash). Clients must `initialize` a
  JSON-RPC session before any tool call and echo the returned `mcp-session-id`
  header on every subsequent request.
- **`scripts/smoke_substrate.py` needs `requests`** (not pinned in a
  `requirements.txt`).
- **The first `docker compose up` builds the image** (`uv sync` downloads the
  Python dep tree) — multi-minute once; later ups reuse the cached layer.
