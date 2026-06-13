# Consumer integration guide

> How your app talks to the brain, in brief — the narrative companion to
> [`consumer-api.md`](./consumer-api.md) (the per-operation reference).

## The consumer surface: `recall` + `doc` + `map`

A consumer app (scout, …) searches with a question, and fetches known documents
deterministically:

- **`recall(query)`** — `GET /recall?q=…` (and the `recall` MCP tool). Hybrid
  retrieval (cosine over pgvector + full-text `tsvector`, fused with RRF) that
  returns top-k chunks. Each chunk is `{id, heading, text, score, path}` —
  `text` carries the meaning (the consumer is an LLM; there is no
  `polarity`/`strength` schema), `score` is reported, not thresholded — your
  consumer decides what counts as relevant — and `id` is the owning document's
  stable id, the bridge to `doc`.
- **`doc(id)`** — `GET /doc?id=…`. One whole document by stable id: the stored
  text **verbatim, byte-exact**, plus a content `version` stamp to cache on.
  Pin pages by id; re-fetch when the stamp moves. 404 on an unknown id.
- **`map()`** — `GET /map`. The synced document tree
  (`{id, title, path, parent_id, version}`): where a consumer discovers the ids
  to pin. Titles/paths are display-only — never lookup keys.

Consumers are **read-only**, and for *search* they never need to know the
brain's folder structure (a *scope*). The full contract — cache rules, 404
semantics, what `version` covers — lives in
[`consumer-api.md`](./consumer-api.md).

## Not a consumer endpoint

`profile(scope)` exists but is **brain-side machinery + an owner tool**: it
powers self-enrichment (assemble a domain → distill a digest that `recall`
surfaces) and backs the authed dashboard where the owner browses their own folders.
Consumers get faithful content, never an assembled view — don't build a dumb
consumer against it.

## The write path

There is **no `capture`**. The only write is **`POST /ingest {url}`**, which
fetches a Notion page, upserts it as a *source*, and wipe-replaces its chunks
(re-embedding with Voyage). Capture = human edit = re-sync are the same operation.
Writes come only from sources.

## Two faces

One service (`brain/api.py`) serves both: plain HTTP (`/ingest`, `/recall`,
`/profile`, `/map`, `/health`) for apps, and MCP at `/mcp` (tools `recall`,
`profile`, `map`) for Claude Code.

## Where to reach the brain (and auth)

Same contract, two addresses depending on where your consumer runs:

- **On the VPS, on `brainnet`** (scout, the dashboard backend, the Claude Code hook):
  call `http://brain:8100` directly — **no token**. The brain's port is never
  published, so being on `brainnet` *is* the authorization; only put services
  you trust on it (there's no per-app auth inside).
- **Off the box** (your laptop, another server): `https://brain.api.{domain}` +
  the bearer token.

This is the same split the dashboard backend uses — it proxies `/api/brain/*` to the
brain so the bearer stays server-side, never in the browser. Full topology +
firewall in [`architecture.md`](./architecture.md).

---

For the full operation reference, schemas, config, and run instructions, see
[`brain.md`](./brain.md) and
[`brain-architecture.md`](./brain-architecture.md). The per-operation spec
companion to this guide is [`consumer-api.md`](./consumer-api.md).
