# Note Legibility & Optional Rewrite

> Feature plan. The *why*, the *shape*, and a build checklist. Lands next to
> [`brain-architecture.md`](./brain-architecture.md) (the brain's settled design)
> and amends one of its settled principles — see [Principle amendment](#principle-amendment).
> Status: **built + deployed to the live brain, enabled.** Phases 1, 2, and 4 are
> implemented and tested (schema + analyzer + ingest fork + config seam; `map`
> health + docs; manual-trigger endpoint + per-source policy + UI). The Phase 0/3
> A/B has been run against the live corpus (see [Eval run](#eval-run--2026-06-11-deployed-live-mechanism-works-but-corpus-too-small-to-set-the-threshold)):
> the mechanism is verified (a grounded structural rewrite lifts the buried-sub-idea
> MRR). The recall@k curve still can't set `legibility.threshold` (recall saturates
> on this corpus), so it's set to **`65`** from the health-score distribution
> (borderline content clusters at 62–63). Owner-writing guidance:
> [`writing-legible-notes.md`](./writing-legible-notes.md).
> **Not yet landed in git** — the change lives on the `note-legibility` worktree
> branch; the live brain image was rebuilt directly from it.

## The problem

Capture is meant to be frictionless: open voice mode, ramble, "dump it in Notion."
No structure, no headings, no consistency — that's the point, and we will not ask
the user to change it (directing your agents should be as easy as taking notes).

But the brain chunks a page **by its own markdown headings** (`store.py:_split_sections`).
A freeform dump with no headings collapses into a **single chunk**, whose embedding
is the mushy average of a whole entry touching many unrelated topics — it matches
everything weakly and nothing strongly. Recall on that degrades to "find the entry
that mentioned X," barely better than keyword search.

So the value the brain can add to messy notes is gated by structure the user won't
provide. The conclusion that drives this whole feature: **the structure has to be
synthesized by the system, not authored by the user** — and the brain is already
built for exactly that move, because `sources.raw_text` is canonical and verbatim
while `chunks` are a derived, disposable index (currency by construction). We can
make the derived index arbitrarily smarter without touching the user's note.

## What we're adding

Two capabilities, one ingest-time LLM call:

1. **Legibility health** — a structured, stored signal per source describing how
   *legible to agents* a note is (not how tidy it looks). Always the cheaper,
   always-useful half: it tells the user what their notes are costing their agents,
   and it gates capability 2.
2. **Optional structural rewrite** — when a note is illegible enough, an LLM rewrite
   that **restructures** the dump into self-describing idea-units the chunker can
   split well. Stored *beside* the original (never replacing it, never written back
   to Notion). Chunks then derive from the rewrite instead of the raw blob.

Health and the rewrite are produced by **the same LLM pass** — segment-and-score is
one call. Health can also gate the rewrite (skip the expensive restructuring on
already-legible pages), so cost tracks need.

## Principle amendment

This amends **Settled Principle #3 — "No write-time LLM"** in
[`brain-architecture.md`](./brain-architecture.md). That was a starting-simplicity
choice, not a permanent tenet. The amended principle:

> **No write-time LLM *by default*.** The base brain remains split + embed + insert.
> Legibility analysis (health + optional rewrite) is an **opt-in** layer at the edge
> of ingest. With it disabled, ingest is byte-for-byte the behavior it is today.

Every other settled principle is **preserved**:

- **Sources are canonical; chunks are derived/disposable** — the rewrite is a new
  derived artifact, not a mutation of the source. `raw_text` stays verbatim.
- **Read-only for consumers** — unchanged.
- **Never write back to Notion** — confirmed long-term. Notion stays the immutable
  original; the rewrite lives only in the brain. (This also means nothing the rewrite
  does is unrecoverable: re-ingest restores the original.)
- **Librarian, not synthesizer** — the rewrite is *structural restructuring of the
  user's own words*, not synthesis/inference/decision. The boundary is enforced by
  the [grounding rule](#design-decisions-settled) below.

## Design decisions (settled)

These were decided in design discussion; they are inputs to the build, not open
questions.

- **Keep both representations.** `raw_text` stays verbatim; the rewrite is a separate
  column. Preserves provenance, gives the A/B both sides to compare, lets drafting
  read the raw voice while recall reads the clean structure.
- **Structural, not stylistic.** The rewrite segments into self-describing idea-units,
  resolves dangling references ("I agree with that" → with *what*), and dedupes within
  the page. It must **not** make the prose read nicely — the user's voice and the raw
  spark are the asset (this is a Twitter-content pipeline; weird phrasing is value).
- **Grounded — no new claims.** The rewrite may only restructure what's there. Every
  claim must trace to `raw_text`. Keeping both representations makes any drift
  auditable via diff.
- **Structured health, not a scalar.** Store sub-signals (see [data model](#data-model-changes)),
  derive a score from them. Actionable feedback, smarter triggering, per-dimension A/B.
- **Opt-in; manual or automatic.** Global enable + mode. Auto fires when health is
  below a threshold. A per-source override can pin a page to "never rewrite."
- **Generic for any notebook.** Nothing here is Twitter- or Notion-specific. Legibility
  is about agent-consumption of *any* source (see [`genericity-rule.md`](./genericity-rule.md)).
  The provider is pluggable, like the embedder.

## Deliberate non-goals (v1)

- **Cross-page legibility.** The real rot in a date-journal is *across* entries — the
  same idea evolving over twenty pages, contradictions over months. Per-source rewrite
  cannot see that (ingest is per-source). It's a genuine future axis, but it means
  cross-source analysis — a much bigger surface. Ship per-page first; let the A/B say
  whether per-page alone moves recall enough before reaching for it.
- **Indexing both raw and rewrite for recall.** Doubles storage and muddies the A/B.
  One clean path: chunk from the rewrite when present, else the raw text.
- **Strong entailment verification of grounding.** v1 relies on a constrained prompt +
  a self-reported `grounded` flag + the auditable diff. A real entailment checker is a
  later hardening, noted not built.

## Data model changes

Additive columns on `sources` (idempotent `ADD COLUMN IF NOT EXISTS`, matching the
existing `db.py` migration style). No change to `chunks`.

```sql
-- The structural rewrite of raw_text. NULL = pass-through (chunk from raw_text).
-- Non-null = the chunker splits THIS instead. Never written back to Notion.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS rewrite_text text;

-- Structured legibility signal. Shape:
--   { "score": 0-100,
--     "dimensions": { "separability": 0-1,      -- are ideas separable, or one blob?
--                     "self_containment": 0-1,  -- self-describing, or reference-rot?
--                     "redundancy": 0-1,        -- 1 = no within-page repetition
--                     "signal_density": 0-1 },  -- extractable content vs noise
--     "notes": ["dangling 'this' in para 3", ...],  -- actionable, per-page guidance
--     "grounded": true }                            -- rewrite added no new claims
ALTER TABLE sources ADD COLUMN IF NOT EXISTS health jsonb;

-- md5(raw_text) that health+rewrite were computed against. Re-ingest of unchanged
-- content reuses the stored analysis instead of re-running the LLM (idempotency:
-- prevents nondeterministic chunk churn under consumers and needless cost).
ALTER TABLE sources ADD COLUMN IF NOT EXISTS analysis_hash text;

-- Per-source override of the global policy: 'auto' (follow global), 'off' (never
-- rewrite — pin to the raw voice), 'manual' (rewrite only on explicit request).
ALTER TABLE sources ADD COLUMN IF NOT EXISTS rewrite_policy text NOT NULL DEFAULT 'auto';
```

### Where each knob lives: secret and policy both runtime, in the DB (env fallback)

The on/off switch and the secret are distinct, but both are runtime values now,
mirroring the **existing** `poll_interval` split (`Config.*` env default, overridden by
a `settings`-table value, resolved per-request):

- **The Anthropic API key — `settings` k/v table, with `ANTHROPIC_API_KEY` env as a
  fallback.** Set/replaced/removed from the Integrations UI exactly like the Notion
  token (`PUT/DELETE /integrations/anthropic`): a stored key wins over the env, resolved
  per ingest by `_active_anthropic_key(pool)`. So deployers needn't bake the secret into
  env — it can be provided from the dashboard. The key is never returned to the client.
- **`legibility.*` — `settings` k/v table, runtime, no restart.** Toggleable from the
  UI exactly like the Notion poll interval:
  - `legibility.enabled` — `"true"`/`"false"` (default false; off = today's behavior).
  - `legibility.mode` — `"auto"` | `"manual"` (default `"auto"`: rewrite fires on its
    own for any page below the threshold; `"manual"` = analyze for health on every
    ingest but only rewrite on an explicit per-page request, see [Manual trigger](#manual-trigger-surface)).
  - `legibility.threshold` — health score below which auto-rewrite fires.
  - `legibility.model` — model id (default `claude-sonnet-4-6`; one model for both the
    health pass and the rewrite).

**The seam resolution (this is the part the plan previously left ambiguous):**

`Config().validate()` does **not** gate on the key — it can't, because both `enabled`
and the key are DB values and `validate()` runs at boot with no pool. Boot stays
key-agnostic. Instead, an `_effective_legibility(pool) -> (enabled, mode, threshold,
model, api_key)` helper — the exact shape of `_effective_poll_interval` — resolves the
live policy and the key (via `_active_anthropic_key`, DB-over-env) at ingest time, and
**treats "enabled but no key" as disabled (pass-through), logging a warning.** This
mirrors the established defense that "a malformed stored value can't wedge syncing off":
flipping the toggle on without providing the secret degrades to today's behavior, it
never crashes ingest. So `validate()` is unchanged; `Config` still reads
`ANTHROPIC_API_KEY` as the env fallback (empty string when unset).

## Ingest flow changes

`upsert_source` gains an analysis step **before** chunking. Pseudocode of the new
order (embedding still happens outside the transaction, as today):

`upsert_source` takes one new optional argument, `force_rewrite: bool = False`, set
only by the [manual-trigger endpoint](#manual-trigger-surface); auto/poll ingest leaves
it false.

```
raw_text          = fetched page text (verbatim, stored as-is)
h                 = md5(raw_text)
enabled, mode, threshold, model = _effective_legibility(pool)   # 'enabled but no key' -> disabled

if enabled and rewrite_policy != 'off':
    if h == stored analysis_hash and not force_rewrite:
        reuse stored health + rewrite_text            # idempotency gate — no LLM
    else:
        health, rewrite = analyze(raw_text, model)    # ONE LLM call (segment + score)
        want_rewrite = force_rewrite or (mode == 'auto' and health.score < threshold)
        if not want_rewrite:
            rewrite = None                            # health stored, rewrite skipped
        store health, rewrite_text, analysis_hash = h
else:
    health, rewrite_text = NULL, NULL                 # base brain, unchanged

chunk_source = rewrite_text or raw_text               # the ONLY behavioral fork
sections     = _split_sections(title, chunk_source)
... embed + wipe-replace chunks as today ...
```

The single behavioral fork is `chunk_source = rewrite_text or raw_text`. Everything
downstream (`_split_sections`, embedding, wipe-replace) is unchanged — the rewrite is
expected to *contain* the markdown headings the splitter already keys on.

Note the three rewrite triggers are now fully disambiguated: **auto** (`mode == 'auto'`
and `health.score < threshold`), **manual** (`force_rewrite`, which also bypasses the
analysis-hash cache so a re-request re-runs even on unchanged text), and **never**
(`rewrite_policy == 'off'`, the per-source pin — see below for how a manual request
interacts with it).

## Read-surface changes

- **`doc(id)` — unchanged.** Still returns `raw_text` **verbatim** — the rewrite is
  not exposed on doc (decided). doc is ground truth; the byte-exact guarantee is
  preserved. (Consequence to document: a recalled chunk's text now comes from the
  rewrite, so it may not be a substring of `doc.text`. This is intended — chunk =
  clean structure, doc = what you actually wrote.)
- **`map()` — gains `health`.** Add the score (nullable) to each source dict so the
  dashboard and apps can surface "your notes are healthy / these three are hurting
  your agents." This is the consumer-visible payoff of putting health in the brain.
- **`recall()` — unchanged contract.** Chunks now derive from the rewrite when present;
  the shape `{id, heading, text, score, path}` is identical.

## Manual trigger surface

`mode: "manual"` and the per-source `'manual'` policy both need a way to say "rewrite
*this* page now." That action gets one endpoint, in the established REST style of
`POST /ingest` and `DELETE /sources/{source_id}`:

```
POST /sources/{source_id}/rewrite
  -> 200 {id, health, rewrote: bool, chunk_count}
```

It re-fetches nothing — it re-analyzes the **already-stored** `raw_text` for that source
and re-derives chunks. Concretely it just calls `upsert_source(..., force_rewrite=True)`
with the source's own stored `raw_text`/`title`/`path`, so it reuses the entire ingest
path (analyze → `chunk_source` fork → embed → wipe-replace) rather than duplicating it.
`force_rewrite` is what bypasses both the auto-threshold check and the analysis-hash
cache, so the rewrite runs even if `mode` is `manual` and even if the text is unchanged
since the last analysis.

**Interaction with the `'off'` pin (the one real precedence decision):** a source with
`rewrite_policy == 'off'` is **not** rewritten even by this endpoint — `'off'` means
"pin to the raw voice," a deliberate human choice that an explicit rewrite request should
not silently override. The endpoint returns `200 {rewrote: false}` with a reason rather
than a `4xx`, so the caller (dashboard button) can show "this page is pinned to raw —
clear the pin first." Clearing the pin (set policy back to `'auto'`/`'manual'`) and
re-requesting is the two-step path; there is no force-past-`'off'`. This keeps `'off'`
meaning exactly one thing.

The endpoint is also what the **Phase 4 dashboard diff view** calls: "rewrite this page"
→ `POST .../rewrite` → show the raw-vs-rewrite diff from the stored columns.

The global on/off (`legibility.enabled`) still applies: with the feature disabled the
endpoint is a `409` (or returns `{rewrote: false, reason: "legibility disabled"}`) —
there is no per-page path that runs the analyzer while the feature is globally off.

## New module / config / deps

- **`brain/brain/legibility.py`** — the analyzer: `analyze(raw_text, model) -> (health, rewrite)`,
  one LLM call, synchronous, wrapped in `asyncio.to_thread` by `upsert_source` (mirrors
  how `embed()` is called). Prompt enforces structural-only + grounded.
- **New dependency + secret:** the Anthropic SDK and `ANTHROPIC_API_KEY`, calling
  `claude-sonnet-4-6` for both the health pass and the rewrite. This is a real
  addition — a new dep and a new secret in deployment — and the feature is opt-in
  partly to keep the base brain free of it.
- **Config:** `Config` gains an `anthropic_api_key` field read from env (empty string
  when unset), alongside the existing Voyage/Notion fields. `Config().validate()` is
  **unchanged** — it does *not* require the LLM key, because `legibility.enabled` is a
  runtime DB setting with no pool at boot (see [the seam resolution](#where-each-knob-lives-secret-in-env-policy-in-the-db)).
  Enforcement moves to `_effective_legibility(pool)`, which resolves the live policy at
  ingest and degrades "enabled but no key" to pass-through. The `legibility.*` settings
  themselves live in the `settings` table, not in env.

## Eval / A/B plan

The trigger policy ("when is a page bad enough to rewrite?") is decided by evidence,
not a guessed threshold. With ~one user this is not production traffic-splitting —
it's a **policy experiment against the real corpus**, using the `test-brain` skill
(which already measures recall quality and shows how a source chunks; see also the
retrieval-eval scorecard noted in `brain-architecture.md` RAG experiments).

The experiment:

1. Take a set of real messy dumps + a set of probe queries with known-relevant entries.
2. Baseline: recall quality (recall@k / precision) with today's heading-only chunking.
3. Treatment: same probes, chunking from the rewrite.
4. Compare per health-dimension. The auto rule becomes "rewrite when health < X **and**
   it measurably lifts recall," with X read off the curve — not picked by feel.

The harness is built: `brain/eval/recall_scorecard.py` (recall@k / precision@k / MRR
over `/recall`, baseline-vs-treatment diff) and `brain/eval/run_ab.py` (the full
in-process A/B against an isolated copy of the corpus — real Voyage + Anthropic,
never touches the live brain). **How to re-run when the corpus grows — including how
to find the "real dumps" and what counts as enough data — is the runbook at
[`../brain/eval/README.md`](../brain/eval/README.md).**

### Eval run — 2026-06-11 (deployed live; mechanism works, but corpus too small to set the threshold)

The feature was deployed to the live brain (image rebuilt for the `anthropic` dep,
container recreated, `legibility.enabled` flipped on) and the one real headingless
dump ("Chainguard") was rewritten in place via `POST /sources/{id}/rewrite` (1 → 7
chunks). A/B over `brain/eval/probes.json` (k=5):

| metric | baseline (off) | treatment (rewrite) | Δ |
|---|---|---|---|
| recall@5 | 1.00 | 1.00 | +0.00 (saturated) |
| precision@5 | 0.24 | 0.46 | **+0.22** |
| MRR | 0.92 | 1.00 | **+0.08** |

- **Mechanism works in the real setting.** The live Anthropic call produced a
  **grounded** (`grounded:true`) structural rewrite — one mushy paragraph-blob → 7
  self-describing `##` idea-units in the author's own words, dangling refs resolved
  ("they"→"Chainguard", "this"→the rebuild situation), no new claims; `notes` nailed
  the real defects. On the live corpus the empty title-stubs create genuine
  competition, so Chainguard's buried "coordination" sub-idea ranked **3rd** as one
  mushy chunk (rr 0.33) and **1st** after the rewrite (rr 1.0) — the exact
  within-dump discrimination the feature is for. `recall@5` stays saturated (the
  relevant source is always in top-5 on this tiny corpus).
- **Still no threshold curve — corpus too small.** Of 30 sources, ~24 are empty
  title-only stubs and the content ones are *already* multi-heading; only Chainguard
  is a genuine dump. One illegible page can't produce a curve.
- **Threshold set to 65 (from the score distribution).** After the empty stubs were
  found to be uncaptured DB-property content and the migrator was fixed to fold those
  properties in (`brain/notion.py`), the corpus grew to ~30 real, topically-
  overlapping sources. Their health scores **cluster at 62–63** for borderline
  one-paragraph content — just above the old `60` cutoff, so auto-mode left them as
  is. So `legibility.threshold` is now **`65`**, chosen from that distribution rather
  than guessed. The recall@k curve still can't refine it (recall saturates even at 30
  sources); re-tune via `run_ab.py` when the corpus grows further.
- **Aside (acted on):** the ~24 "empty stubs" were not junk — they were Notion
  database rows whose content lives in rich_text properties the brain wasn't reading.
  Fixed; they're now real content sources.

## Build checklist

Phased so each step is independently verifiable. Earlier phases de-risk later ones.

> **Implementation status** (2026-06-11). Phases 1, 2, and 4 are implemented and
> tested (`brain/tests/test_legibility.py`, 28 tests; the brain suite is green at
> 64). The dashboard surfaces (home health badge, integrations settings card, per-source
> diff view) typecheck. Phase 0 and Phase 3 are the eval phases: they need the live
> brain + `ANTHROPIC_API_KEY` + the real messy dumps, so they're left unchecked —
> the methodology stands in [Eval / A/B plan](#eval--ab-plan), and `threshold`
> defaults to `65` (set from the corpus health-score distribution, not a recall
> curve — see the Eval run).

### Phase 0 — Eval baseline (so we can measure) — needs the live corpus + key
- [ ] Assemble a probe set: real dumps + queries with known-relevant sources. → verify: set committed/fixtured.
- [ ] Stand up / adopt a recall-eval scorecard (recall@k, precision) via `test-brain`. → verify: produces numbers on the current brain.
- [ ] Record the heading-only baseline. → verify: baseline numbers captured.

### Phase 1 — Schema + analyzer (off by default)
- [x] Add the four `sources` columns (idempotent DDL in `db.py`). → verified: `apply_schema` runs clean on the existing DB; `test_schema_has_legibility_columns`.
- [x] Add `legibility.py` analyzer: one call returns structured health + structural, grounded rewrite. → verified mechanically (parse + clamp + heading-bearing rewrite) with a mocked SDK; the live voice/grounding quality is the Phase-3 eval.
- [x] Wire into `upsert_source`: `force_rewrite` arg, analysis-hash gate, `chunk_source = rewrite_text or raw_text`. → verified: disabled ingest is byte-identical (`test_disabled_is_byte_identical` + the 36 pre-existing tests still pass); enabled, a headingless dump yields multiple chunks.
- [x] Config + resolver: `Config.anthropic_api_key` (env); `_effective_legibility(pool)` mirroring `_effective_poll_interval`, degrading "enabled but no key" to pass-through. → verified: `validate()` unchanged; boots without the key; toggle-on-without-key warns + passes through (no crash).

### Phase 2 — Read surface
- [x] Add `health` to `map()` output. → verified: `/map` carries the structured `health` (score in it), null for un-analyzed sources.
- [x] Document the doc-vs-chunk text divergence in `consumer-api.md`. → done (doc note + map `health` shape).

### Phase 3 — A/B + policy — needs the live corpus + key
- [ ] Run raw-vs-rewrite on the Phase-0 scorecard. → verify: per-dimension deltas recorded.
- [ ] Set `legibility.threshold` from the curve; tune the prompt against failures. → verify: chosen threshold lifts recall on held-out probes.

### Phase 4 — Surfacing, override, guidance
- [x] Dashboard health view: score + actionable `notes`; rewrite diff (raw vs rewrite). → built: home score badge (reasons in tooltip) + the `#legibility/<id>` view (health + reasons + raw-vs-rewrite diff). Typecheck-verified; UI behavior needs the live dashboard.
- [x] `POST /sources/{id}/rewrite` manual-trigger endpoint (`force_rewrite=True`; respects the `'off'` pin and global disable). → verified: rewrites an unchanged page on demand; `{rewrote: false}` for an `'off'` page and a 409 when globally disabled.
- [x] Per-source `rewrite_policy` override (incl. 'off' = pin to raw voice). → verified: an 'off' page is never rewritten, even by the manual endpoint; set via `PUT /sources/{id}/rewrite-policy`.
- [x] Guidance doc: how to write notes that power the rewrite well — framed as help, not a requirement. → [`writing-legible-notes.md`](./writing-legible-notes.md); linked from the badge tooltip's destination and the legibility view.

### Also built (completing the UI-toggle seam the config section calls for)
- [x] `legibility.*` status on `GET /integrations` + `PUT/DELETE /integrations/legibility` (set/reset the runtime policy from the UI, exactly like the poll interval).
- [x] The Anthropic API key set/removed from the UI via `PUT/DELETE /integrations/anthropic` (validated against the API before storing, like the Notion token; a stored key wins over the `ANTHROPIC_API_KEY` env). Status (`has_key`, `key_source`) rides on `GET /integrations` under `legibility`.
- [x] `GET /sources/{id}/rewrite` owner read (stored raw/rewrite/health/policy) — the diff view's data source.

## Decisions (resolved)

The forks that were open are now settled — the plan is decision-complete. The only
value still set empirically is `legibility.threshold` (read off the Phase 3 curve).

1. **Model — one model, `claude-sonnet-4-6`,** for both the health pass and the
   rewrite. At ~a page/day the cost gap over a cheaper model is pennies, so quality
   (voice preservation + grounding) wins over a two-tier split.
2. **`doc()` stays verbatim-only.** The rewrite is an internal chunking input, not
   consumer content; doc remains byte-exact ground truth.
3. **Health is LLM-only,** computed in the same pass as the rewrite. No zero-LLM
   heuristic tier — health is null on un-analyzed sources; one scorer, less code.
4. **Default mode is automatic.** Once enabled, any page below the threshold is
   rewritten without a manual trigger (matches "as easy as taking notes"); the
   per-source `'off'` override and the diff view are the safety net.
5. **Config seam — key and policy both runtime in the DB (env fallback).** The Anthropic
   key is a `settings`-table credential set from the UI (`PUT/DELETE /integrations/anthropic`),
   with `ANTHROPIC_API_KEY` env as a fallback; `legibility.*` are runtime `settings`-table
   values. `validate()` stays key-agnostic; `_effective_legibility(pool)` resolves the key
   (`_active_anthropic_key`, DB-over-env) + policy at ingest and degrades "enabled but no
   key" to pass-through. Mirrors the existing `poll_interval` and Notion-token splits, so
   no new pattern is introduced.
6. **Manual rewrite is one endpoint, and `'off'` always wins.** `POST /sources/{id}/rewrite`
   forces a rewrite of stored `raw_text` via `force_rewrite=True`, bypassing the
   threshold and the hash cache — but a `'off'`-pinned page is never rewritten, even
   here (clear the pin first). `'off'` means exactly one thing.
