# Consumer API reference

> The consumer contract: what each operation returns and the rules for using it
> (cache semantics, 404 handling). Service-side detail (config, run
> instructions, internals) lives in [`brain.md`](./brain.md) and
> [`brain-architecture.md`](./brain-architecture.md).

The brain serves both faces from one service (`brain/api.py`): plain HTTP and MCP
at `/mcp`.

## Operations

| Operation | HTTP | MCP tool | Read/write | Consumer? |
|---|---|---|---|---|
| Recall | `GET /recall?q=&scope=&k=&complete=` | `recall` | read | **yes — search** |
| Doc | `GET /doc?id=` | `doc` | read | **yes — deterministic whole-document fetch** |
| Map | `GET /map?scope=` | `map` | read | **yes — discovery (ids, versions)** |
| Profile | `GET /profile?scope=&budget=` | `profile` | read | no — brain machinery + owner |
| Ingest | `POST /ingest {url}` | — | write | the write path |
| Health | `GET /health` | — | read | liveness |

## Recall — search

`recall(query)` is the search read: hybrid retrieval (cosine over pgvector +
full-text `tsvector`, fused with RRF) returns top-k chunks. Pass
`complete=true` for the brain's own everything-relevant cutoff (no consumer
score knobs).

```
Chunk { id:      str    # the OWNING DOCUMENT's stable id — the doc()/map() key
        heading: str    # the section heading
        text:    str    # the section body — meaning lives here (no typed fields)
        score:   float  # reported, not thresholded — the consumer decides relevance
        path:    str }  # the source's place in the tree (display/provenance only)
```

There are **no** `fact`/`name`/`polarity`/`strength`/`valid_at`/`invalid_at`
fields and **no** episode bodies — currency is guaranteed by construction
(wipe-replace per source), so there is no bi-temporal machinery to expose.

## Doc — deterministic whole-document fetch

`doc(id)` returns one document by its stable id (the origin's immutable page
uuid — renames never move it):

```
{ id:      str   # the stable id, dashed-canonical
  title:   str   # display only
  path:    str   # display only — can change under a stable id (ancestor renames)
  version: str   # content stamp: moves iff {title, text} change — THE cache key
  text:    str } # the stored document VERBATIM, byte-exact (never chunk-reassembled)
```

`400` on a missing/malformed id, `404` on an unknown one (`{"error": ...}`
bodies). No other parameters — a dumb single-row read, no LLM, no knobs.

**Cache rules:** pin pages by `id`; cache `text` keyed by the `version` from the
*same* `/doc` response (use `/map`'s `version` only as a change hint — the two
reads are independent point reads, not a snapshot). `version` covers exactly the
served `{title, text}`: it never moves on a mere re-sync or a path change, and
byte-exactness is relative to the *stored* text (ingest's flattening/sanitizing
happens before storage). A `404` on a pinned id means the document left the
synced set — treat it loudly, not as an empty result.

## Map — discovery

`map(scope=None)` returns the source tree, ordered by path:

```
{ id:        str         # the stable id to pin
  title:     str         # display only
  path:      str         # display only
  parent_id: str | null  # parent document's id IF that parent is synced, else null
  version:   str }       # same stamp doc() serves — diff to spot changes cheaply
```

This is where a consumer discovers ids; titles/paths are never lookup keys.
`parent_id` null is overloaded (true root *or* parent-not-synced) — a linkage
hint, not an authoritative tree. No chunk contents, no sync metadata.

## Profile — not a consumer endpoint

`profile(scope)` returns an assembled `Context{text, sources, truncated}` for a
path subtree. Assembly/synthesis is exactly what consumers don't get — it stays
**brain-side machinery + owner tooling**.

## Ingest — the write path

`POST /ingest {url}` fetches a Notion page, upserts it as a source, and
wipe-replaces its chunks. There is **no `capture`**.

---

The detailed per-operation spec (request/response shapes, scope semantics,
`Context`, config, run instructions) lives in
[`brain.md`](./brain.md) and
[`brain-architecture.md`](./brain-architecture.md). For the narrative how-to,
see [`consumer-integration.md`](./consumer-integration.md).
