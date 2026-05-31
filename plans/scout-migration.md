# Plan: Migrate scout to the document-substrate brain

## Status: planned — downstream of the Phase-1 cutover

The brain was rebuilt from a graph (graphiti-core / FalkorDB) onto a **Postgres +
pgvector document substrate** (see [`document-substrate-exploration.md`](./document-substrate-exploration.md)
and [`../brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md)). The contract scout
consumes **changed shape**, so scout — which lives in its own repo — needs to migrate.
This doc is the spec for that migration. Nothing here is brain-side work; it's what
the scout codebase must change.

---

## What changed (old brain → new brain)

| | Old (graphiti graph) | New (pgvector document substrate) |
|---|---|---|
| **Backend** | graphiti-core over FalkorDB | Postgres + pgvector (transparent to scout, but the *contract* differs) |
| **Read shape** | `recall` returned **facts**: `{fact, polarity, strength, valid_at, score}` | `recall` returns **chunks**: `{heading, text, score, path}` — *prose*, no schema |
| **The "profile" read** | `profile()` (no args) dumped **all facts** about the user | **gone for consumers.** `profile(scope)` exists but is brain-internal/owner-only — scout must NOT call it (it leaks the brain's folder taxonomy) |
| **Write path** | `capture(text)` wrote into the graph | **removed.** Consumers are read-only; the brain is fed only by sources (Notion sync) |
| **Structure** | polarity/strength tags drove `hard→gate, soft→weight` | no tags — the meaning is *in the text*; scout's LLM reads "avoids fintech — hard dealbreaker" from prose |

The **librarian/analyst split is unchanged**: the brain returns raw, faithful content
and never a verdict; scout does *all* interpretation (gates, dedup, green/yellow/red).
What changed is only the *format* of what the librarian hands over — prose chunks
instead of tagged facts.

---

## The contract scout codes against now

**One read: `recall(query)`.** Scout asks a natural-language question; the brain
returns the relevant chunks. Scout never needs to know the brain's internal structure
(no scope, no folder names).

- **HTTP:** `GET /recall?q=<question>&k=<n>` →
  `{"chunks": [{"heading": str, "text": str, "score": float, "path": str}, ...]}`
  (an optional `scope` param exists but scout should not use it — see Boundaries).
- **MCP:** the `recall` tool, same shape, for LLM-harness consumers.
- **Base URL:** `http://127.0.0.1:8100` locally; `https://brain.api.<domain>` on the
  VPS (bearer token at the edge — set `BRAIN_BEARER_TOKEN`).
- **Do NOT use** the old reference client `migrate/graphiti_clients.py` — it speaks the
  dead graph contract. Code against the plain HTTP shape above (it's a few lines).

---

## How scout's reasoning changes

Old scout read structured facts and turned `strength` into gates. New scout reads
**chunk text** and reasons over it directly — the dealbreakers, gates, and
preferences are stated in the prose. Concretely, to assess a candidate company:

1. Ask the brain what the user wants — one or a few targeted recalls, e.g.:
   - `recall("what kind of company does the user want to work at")`
   - `recall("what roles and titles does the user want")`
   - `recall("what does the user avoid / hard dealbreakers")`
2. Read the returned chunk `text` (the criteria, in the user's own words).
3. Reason over the candidate against that text and emit the verdict
   (green / yellow / red) with the matching evidence — **all in scout**, as today.

The brain gives scout *the criteria*; scout does the *judging*.

---

## Migration steps (scout-side checklist)

1. **Swap the read.** Replace fact-shaped consumption (`fact`/`polarity`/`strength`)
   with chunk-shaped consumption (`heading`/`text`/`score`/`path`). Reason over
   `text`, not over tags.
2. **Drop `profile()` and any scope knowledge.** Replace any "dump the profile" call
   with one or more `recall(query)` calls. Scout must not hardcode or discover folder
   paths.
3. **Drop `capture`.** Scout is read-only; it never writes to the brain. Anything the
   user should "remember" enters the brain as a *source*, through the human — not via
   scout.
4. **Repoint the client.** Talk to `GET /recall` (or the MCP `recall` tool) at the new
   base URL with the bearer; delete the old graph client usage.
5. **Rewrite the gating prompt** to read criteria from prose and produce
   green/yellow/red, since `hard`/`soft` are no longer separate fields.
6. **Smoke it** against a live brain: ingest the user's job-fit page(s), then have
   scout assess a known-good and known-bad company and confirm the verdicts.

---

## Boundaries (what scout must NOT do)

- **Never write back** to the brain (no `capture`); consumers are read-only.
- **Never pass a `scope` it had to "know."** `recall(query)` is the whole interface —
  if scout finds itself needing to name "Job Hunting," that's a smell. The brain's
  taxonomy is the brain's business.
- **Never expect synthesis from the brain.** It returns content; scout reasons. There
  is no "ask the brain for a verdict" call by design.

---

## Known gaps / sequencing (don't start until these are understood)

- **Completeness for gating.** `recall(query)` returns the top-k *relevant* chunks —
  for a hard-gating task, a relevant criterion could in principle fall outside top-k.
  Near-term mitigation: scout issues a few targeted recalls (criteria / titles /
  avoid-list) and/or a generous `k`. A first-class "return everything related"
  (relevance-threshold) mode on `recall` is the planned successor — see
  [`document-substrate-exploration.md`](./document-substrate-exploration.md) "Future
  limits of `recall`." Until then, cover the bases with multiple questions.
- **The corpus must be ingested.** Scout can only recall what's in the brain. The
  user's job-fit docs (e.g. *Target role*, *Target company*) must be ingested first
  (Phase 1 is manual `POST /ingest {url}`; auto-sync is a later phase).
- **Whole-page chunks (Phase 1).** Recall currently returns whole pages, not tight
  sections; scores are coarse but ranking is correct. Section-splitting (later) sharpens
  this — no scout change needed when it lands; results just get more precise.
- **Deploy + auth.** The brain must be reachable (VPS deploy + Caddy bearer) before
  scout can hit it in production; local dev needs none.
