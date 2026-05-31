# Consumer integration guide

> **Rewritten for the pgvector contract.** The brain is a **Postgres + pgvector
> document store** — no graph, no `capture`, no scored facts. This file is now a
> short pointer; the live, detailed contract lives in
> [`../brain/README.md`](../brain/README.md) and
> [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md).

How your app talks to the brain, in brief.

## The consumer surface is `recall(query)`

A consumer app (scout, …) asks a question and gets back the relevant sections:

- **`recall(query)`** — `GET /recall?q=…` (and the `recall` MCP tool). Hybrid
  retrieval (cosine over pgvector + full-text `tsvector`, fused with RRF) that
  returns top-k chunks. Each chunk is `{heading, text, score, path}` — `text`
  carries the meaning (the consumer is an LLM; there is no `polarity`/`strength`
  schema), and `score` is reported, not thresholded — your consumer decides what
  counts as relevant.

That's the whole consumer contract. Consumers are **read-only** and never need to
know the brain's folder structure (a *scope*).

## Not consumer endpoints

`profile(scope)` and `map(scope)` exist but are **brain-side machinery + owner
tools**, not consumer endpoints: `map` powers sync reconciliation/maintenance,
`profile` powers self-enrichment (assemble a domain → distill a digest that
`recall` surfaces), and both back the authed PWA where the owner browses their own
folders. Don't build a dumb consumer against them.

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
