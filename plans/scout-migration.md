# Plan: Migrate scout to the document-substrate brain

## Status: planned — downstream of the Phase-1 cutover
## Amended 2026-06-04: the consumer surface is now `recall` + `doc` + `map`

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
| **Read shape** | `recall` returned **facts**: `{fact, polarity, strength, valid_at, score}` | `recall` returns **chunks**: `{id, heading, text, score, path}` — *prose*, no schema; `id` is the owning document's stable id |
| **The "profile" read** | `profile()` (no args) dumped **all facts** about the user | **gone for consumers.** `profile(scope)` exists but is brain-internal/owner-only — scout must NOT call it (it leaks the brain's folder taxonomy) |
| **Write path** | `capture(text)` wrote into the graph | **removed.** Consumers are read-only; the brain is fed only by sources (Notion sync) |
| **Structure** | polarity/strength tags drove `hard→gate, soft→weight` | no tags — the meaning is *in the text*; scout's LLM reads "avoids fintech — hard dealbreaker" from prose |

The **librarian/analyst split is unchanged**: the brain returns raw, faithful content
and never a verdict; scout does *all* interpretation (gates, dedup, green/yellow/red).
What changed is only the *format* of what the librarian hands over — prose chunks
instead of tagged facts.

---

## The contract scout codes against now

**Three reads.** `recall(query)` for search; `map()` for discovering documents;
`doc(id)` for fetching one whole document deterministically. All read-only, all
knob-free (scout states *what* it wants, never how the brain ranks or cuts).

- **Recall (search):** `GET /recall?q=<question>&k=<n>&complete=<bool>` →
  `{"chunks": [{"id": str, "heading": str, "text": str, "score": float, "path": str}, ...]}`.
  Scout asks a natural-language question; the brain returns the relevant chunks.
  `complete=true` asks the brain for everything *it* judges relevant (its own
  cutoff; `k` stays a safety cap). `id` is the owning document's stable id — the
  bridge to `doc` when a hit warrants reading the whole page. (An optional
  `scope` param exists but scout should not use it — see Boundaries.)
- **Doc (deterministic fetch):** `GET /doc?id=<stable-id>` →
  `{"id", "title", "path", "version", "text"}`. `text` is the stored document
  **verbatim, byte-exact** — never reassembled from chunks — so pinned content
  (e.g. a frozen email-template paragraph) round-trips untouched. `version` is a
  content stamp that moves **iff** the served `{title, text}` change: never on a
  mere re-sync, never on a path change. `400` malformed id, `404` unknown id
  (`{"error": ...}` bodies).
- **Map (discovery):** `GET /map` →
  `{"sources": [{"id", "title", "path", "parent_id", "version"}, ...]}` — the
  synced document tree. This is where scout finds the ids to pin. `parent_id`
  links to the parent document *when that parent is itself synced*, else null
  (null is overloaded: true root or parent-not-synced — a hint, not an
  authoritative tree). `version` is the same stamp `doc` serves.
- **MCP:** the `recall` / `doc` / `map` tools, same shapes, for LLM-harness
  consumers.
- **Base URL:** `http://127.0.0.1:8100` locally; `https://brain.api.<domain>` on the
  VPS (bearer token at the edge — set `BRAIN_BEARER_TOKEN`).
- **Do NOT use** the old reference client `migrate/graphiti_clients.py` — it speaks the
  dead graph contract. Code against the plain HTTP shapes above (it's a few lines).

### Why the surface grew (the 2026-06-04 amendment)

The original spec said "one read: `recall(query)`" and walled off `map` as
owner-only. That wall conflated two different things. What consumers must never
get is an **assembled/synthesized view** (`profile`) or **ranking knobs** —
that line still holds. What scout *deterministically* needs is different:
whole documents it can pin by a stable id and cache by a version stamp, because
top-k search is the wrong tool for "give me exactly this frozen template,
byte-exact, every run." So:

- `doc(id)` is the new primitive: pin by id, fetch whole, cache by `version`.
- `map` opens to consumers **as a discovery surface** — ids are the keys;
  titles/paths in it are display-only. Fuzzy/title-based lookup stays forbidden;
  `map` exists precisely so scout never has to guess from titles.
- `recall` chunks now carry `id` so a search hit can escalate to its whole
  document without title/path matching.

### Pin/cache rules (normative)

- **Pin by `id`** (the origin's immutable page uuid — Notion renames never move
  it). Get ids from `/map` once (or a recall hit's `id`); store them in config.
- **Cache `text` keyed by the `version` from the same `/doc` response.** Use
  `/map`'s `version` only as a cheap change hint to decide *whether* to
  re-fetch. `/map` and `/doc` are independent point reads, not a snapshot — a
  re-sync can land between them; re-keying on `/doc`'s own response makes that
  race harmless.
- **`version` covers `{title, text}` only.** A `path` change (ancestor rename)
  does not move it; byte-exactness is relative to the *stored* text (ingest
  flattens/sanitizes before storage — what's pinned is what the brain stored).
- **`404` on a pinned id is a loud failure**, not an empty result: the document
  left the synced set (or was never ingested). Fail the run; don't silently
  skip a gate's source material.
- **The brain has no upstream-deletion reconciliation today**: a page deleted or
  unshared in Notion just stops re-syncing — its last-synced content keeps
  serving with a stable `version`. "Version unchanged" means "content
  unchanged," not "still exists upstream."

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
- **Never call `profile`.** Assembled/synthesized views stay owner-only; scout
  gets faithful content (`recall` chunks, whole `doc`s) and reasons itself.
- **Never look documents up by title or path.** Ids are the only keys: from
  `/map`, a recall hit's `id`, or pinned config. Titles/paths are display-only
  and change under renames; ids never do.
- **Never pass a `scope` it had to "know" to `recall`.** For *search*, the
  question is the whole interface — if scout finds itself needing to name
  "Job Hunting" to make search work, that's a smell. (Reading structure from
  `/map` for *discovery/pinning* is sanctioned; feeding it back into recall as
  a ranking lever is not.)
- **Never tune brain internals.** No score thresholds, no cutoffs — `complete=true`
  states intent and the brain owns the judgment.
- **Never expect synthesis from the brain.** It returns content; scout reasons. There
  is no "ask the brain for a verdict" call by design.

---

## Known gaps / sequencing (don't start until these are understood)

- **Completeness for gating.** `recall(query)` returns the top-k *relevant* chunks —
  for a hard-gating task, a relevant criterion could in principle fall outside top-k.
  Mitigations now exist on the contract: `complete=true` (the brain returns
  everything it judges relevant), and — for criteria that live in a *known*
  document — pin it and read the whole thing via `doc(id)` instead of hoping
  search surfaces every section. Multiple targeted recalls remain good practice.
- **The corpus must be ingested.** Scout can only recall what's in the brain. The
  user's job-fit docs (e.g. *Target role*, *Target company*) must be ingested first
  (Phase 1 is manual `POST /ingest {url}`; auto-sync is a later phase).
- **Whole-page chunks (Phase 1).** Recall currently returns whole pages, not tight
  sections; scores are coarse but ranking is correct. Section-splitting (later) sharpens
  this — no scout change needed when it lands; results just get more precise.
- **Deploy + auth.** The brain must be reachable (VPS deploy + Caddy bearer) before
  scout can hit it in production; local dev needs none. Note the bearer is one
  edge token for the whole brain — "profile is owner-only" is a contract
  boundary, not per-endpoint auth; scout honors it by construction.
- **`parent_id` starts null.** It is populated at (re-)ingest from the origin's
  parent link; rows synced before this amendment carry null until the next
  re-ingest. Scout must not gate behavior on `parent_id` yet — treat it as a
  progressively-filling hint.
- **`/doc`/`/map` versions are read-time hashes.** Cheap at the current corpus
  size; if `/map` ever gets hot at thousands of documents, the planned fix is a
  stored content-hash column folded into a future re-ingest — a brain-side
  optimization with no contract change.
