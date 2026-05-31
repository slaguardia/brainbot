# Consumer API reference

> **Rewritten for the pgvector contract.** The brain is a **Postgres + pgvector
> document store** — no graph, no `capture`, no scored facts with
> `polarity`/`strength`, no episode bodies. This file is now a short pointer; the
> live, detailed spec lives in [`../brain/README.md`](../brain/README.md) and
> [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md).

The brain serves both faces from one service (`brain/api.py`): plain HTTP and MCP
at `/mcp`.

## Operations

| Operation | HTTP | MCP tool | Read/write | Consumer? |
|---|---|---|---|---|
| Recall | `GET /recall?q=&scope=&k=` | `recall` | read | **yes — the consumer surface** |
| Profile | `GET /profile?scope=&budget=` | `profile` | read | no — brain machinery + owner |
| Map | `GET /map?scope=` | `map` | read | no — brain machinery + owner |
| Ingest | `POST /ingest {url}` | — | write | the write path |
| Health | `GET /health` | — | read | liveness |

## Recall — the consumer surface

`recall(query)` is the only call a dumb consumer needs. Hybrid retrieval (cosine
over pgvector + full-text `tsvector`, fused with RRF) returns top-k chunks:

```
Chunk { heading: str    # the section heading
        text:    str    # the section body — meaning lives here (no typed fields)
        score:   float  # reported, not thresholded — the consumer decides relevance
        path:    str }  # the source's place in the tree (provenance)
```

There are **no** `fact`/`name`/`polarity`/`strength`/`valid_at`/`invalid_at`
fields and **no** episode bodies — currency is guaranteed by construction
(wipe-replace per source), so there is no bi-temporal machinery to expose.

## Profile / Map — not consumer endpoints

`profile(scope)` returns an assembled `Context{text, sources, truncated}` for a
path subtree; `map(scope)` returns the `(path, title)` source tree. Both require
the caller to know a *scope*, so they are **brain-side machinery + owner tools**,
not part of the consumer contract.

## Ingest — the write path

`POST /ingest {url}` fetches a Notion page, upserts it as a source, and
wipe-replaces its chunks. There is **no `capture`**.

---

The detailed per-operation spec (request/response shapes, scope semantics,
`Context`, config, run instructions) lives in
[`../brain/README.md`](../brain/README.md) and
[`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md). For the narrative how-to,
see [`consumer-integration.md`](./consumer-integration.md).
