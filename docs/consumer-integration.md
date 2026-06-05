# Consumer integration guide

> **Rewritten for the pgvector contract.** The brain is a **Postgres + pgvector
> document store** — no graph, no `capture`, no scored facts. This file is now a
> short pointer; the live, detailed contract lives in
> [`../brain/README.md`](../brain/README.md) and
> [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md).

How your app talks to the brain, in brief.

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
[`../plans/scout-migration.md`](../plans/scout-migration.md).

## Not a consumer endpoint

`profile(scope)` exists but is **brain-side machinery + an owner tool**: it
powers self-enrichment (assemble a domain → distill a digest that `recall`
surfaces) and backs the authed PWA where the owner browses their own folders.
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

---

For the full operation reference, schemas, config, and run instructions, see
[`../brain/README.md`](../brain/README.md) and
[`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md). The per-operation spec
companion to this guide is [`consumer-api.md`](./consumer-api.md).
