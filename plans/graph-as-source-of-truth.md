# Plan: Graph as the single source of truth (Path A)

## Status: planned — not started

Everything leaving the brain as agent-feeding knowledge must come from the
graph. Today it doesn't: `profile()` returns raw episode **bodies**, and
`recall()` returns episode bodies alongside facts, because the extractor drops
negatives and policies (see [`../LEARNINGS.md`](../LEARNINGS.md), Chapter 3).
That body-dump quietly made the captured text the source of truth and
circumvented the database the brain exists to be.

This plan makes the **graph** faithful enough to read from — capturing the
negatives and *strength* it currently loses — and then rebuilds the read paths
to source everything from it. It restores the original
[`brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md) "Item 2" design (profile from
`RELATES_TO` facts), which was abandoned only because the graph wasn't faithful
yet.

---

## The model we settled on (read this first)

The whole design follows from one split:

```
BRAIN (librarian)                         CONSUMER e.g. scout (decider, an LLM)
─────────────────                         ──────────────────────────────────────
returns FACTS, each carrying          →   takes a target (a company, an article…)
 • polarity  (positive / negative)        × the facts, and REASONS:
 • strength  (hard / soft)                  hard fact missed  → red
never emits a verdict                       soft fact missed  → yellow
                                            → green / yellow / red
```

Three consequences that resolve every design fork:

1. **"Wall vs. weight" is not a brain decision — it's the `strength` value.**
   Recording *how hard* the user holds something is a fact about them
   (`ARCHITECTURE.md` principle #4). The brain stores `strength`; the consumer
   turns `hard → gate`, `soft → weight`. This handles multi-user for free: the
   same schema stores *your* "location = hard" and someone else's
   "location = soft" with zero changes — location is never assumed to be a gate.

2. **The consumer is an LLM, not a query engine — so we don't over-structure.**
   Hand an LLM `"preferred verticals are A, B, C, D (held hard)"` and a fintech
   company, and it reasons "not in the list → lean red" on its own. We do **not**
   need `Constraint` nodes, an exception engine, or precedence logic in the
   brain — gates, exceptions, and collisions are all the consumer's reasoning.
   **Everything is a fact carrying `polarity` + `strength`.** (This dissolves the
   old "Constraint node" idea entirely — see Decisions.)

3. **Store facts for LLM-legibility, not deterministic queryability.** The `fact`
   string is natural language ("Steve LaGuardia avoids fintech"); `polarity`/
   `strength` are structured hints. That's the right shape for feeding a reasoner.

The one thing the brain still must protect: a **closed set** ("allowed verticals
are *exactly* these four") must stay legible as a set, not be shattered into
disconnected likes — otherwise the consumer can't tell a boundary is closed. We
accept the LLM-reads-`strength=hard` approximation for v1 and log the exact-
closed-set question as a deferred sharp edge (see bottom).

---

## Why this is viable now (verified)

The `graphiti-core` we already run supports the full mechanism:
- `add_episode(..., entity_types=, edge_types=, edge_type_map=, custom_extraction_instructions=)` — we currently pass only `entity_types` + `custom_extraction_instructions`.
- `edge_type_map: dict[(source_label, target_label), [edge_type_names]]` selects which typed relationships are allowed between which entity types.
- Custom edge **attributes are extracted and persisted**: when a matched edge type's Pydantic model has fields, graphiti runs a dedicated `extract_attributes` pass and stores them on the edge (`graphiti_core/utils/maintenance/edge_operations.py`).
- Every fact edge already carries `episodes` (source-capture uuids) + `created_at` — so provenance is free when we want it (the debug toggle, B.2).

So `polarity` + `strength` on a typed edge is expressible with the engine as-is.
No dependency bump.

## Definition of done

In the `brain` graph, after re-ingesting the real target-role document:
1. The **avoid-list** is present as graph facts (negatives), not only in the body.
2. The **vertical gate** survives as `strength=hard` facts in the graph (held
   hard), not only in the body.
3. `profile()` returns a **flat list of facts from the graph**, each with
   `polarity`/`strength`. No episode-body dump. No constraints object.
4. `recall()` returns graph facts only **by default**; episode bodies/source come
   back **only** when an explicit debug flag is passed.
5. A faithfulness diff (graph-derived profile vs. the old body-dump) shows nothing
   high-signal lost: TS/SCI clearance, the avoid-list, and the gate-as-hard all
   survive as facts with the right `strength`.

---

## Guardrails (do not violate)

- **Generic, no schema lock-in** (`docs/genericity-rule.md`; `config.py` entity-types comment).
  No career-specific edge types (`Targets`, `Avoids`, …). The only structure we
  add is the two **domain-agnostic dimensions** `polarity` + `strength`, which
  apply to health, money, relationships, anything.

- **Preserve strength, not decisions** (`ARCHITECTURE.md` principle #4).
  Record *how strongly* the user holds something. Do **not** encode what an app
  should *do* about it. Concretely: the current source text says a gate triggers
  "an automatic skip with no outreach and no tracker entry" — *"outreach" and
  "tracker" are scout-app actions leaking into the brain.* Store `strength=hard`;
  the consumer decides what skipping means. (Also a Notion-source tweak — C.1.)

- **Librarian, not synthesizer** (`ARCHITECTURE.md` principle #6).
  `profile()` returns structured facts, not synthesized prose. The consumer's LLM
  reasons over them.

- **Surgical** (`CLAUDE.md` §3). The body-dump rationale is woven through several
  docstrings/docs. Update the ones this change falsifies; don't refactor adjacent
  code.

---

## Workstream A — Make the graph faithful

Sequenced first. Do not touch the read paths (B) until A is verified, or you
reintroduce the blind spot under a new name.

### Task A.1 — Extract negatives and avoidances

**File:** `brain/brain/config.py` (`DEFAULT_EXTRACTION_INSTRUCTIONS`)

The override pushes for concepts/values/goals but says nothing about *negative*
relationships. Add a generic, any-domain instruction to extract avoidances,
rejections, exclusions, and dislikes as first-class facts — "the owner
avoids/rejects/will-not X" is as important to record as "the owner seeks X."
Keep wording polarity-neutral, not career-specific.

**Verify:** re-ingest the target-role doc (C.1), then query the graph: negatives
like "avoids fintech," "avoids pure coding roles," "skips onsite/hybrid outside
the Bay Area" appear as `RELATES_TO` facts. (Before: absent.)

### Task A.2 — Typed edge carrying `polarity` + `strength`

**Files:** `brain/brain/client.py` (define the edge type + map, expose them),
`brain/brain/service.py` (`_add` passes `edge_types` + `edge_type_map`).

Define a single, **generic** typed edge with attributes the extractor fills:

```python
class Asserts(BaseModel):
    """A stance the owner holds about a topic/thing the brain should remember."""
    polarity: str  # "positive" (seeks/values/accepts) | "negative" (avoids/rejects)
    strength: str  # "hard" (dealbreaker/gate/requirement) | "soft" (preference)
```

Map it broadly so it applies across domains, e.g. `{("Entity", "Entity"):
["Asserts"]}`. The relationship *verb* still lives in the edge's `fact` string;
the attributes add the two dimensions the body-dump was covering for. (Single
generic edge, not named verbs — see Decisions #1.)

**Verify:** query an edge's `attributes`; `strength`/`polarity` populated. The
vertical gate's facts carry `strength=hard`; a mild preference carries
`strength=soft`.

### Task A.3 — Keep closed sets legible (anti-shatter)

**Files:** `brain/brain/config.py` (extraction note) and/or `decompose.py`.

We are **not** adding `Constraint` nodes (the librarian model dissolved that —
see Decisions #2). But benign decomposition still risks turning "allowed
verticals = *exactly* {A,B,C,D}" into four disconnected "targets X" facts, losing
the *closed* signal. Lightest touch: ensure the rewrite/extraction keeps a
closed/defining set expressed as one coherent fact (the decomposer already keeps
"defining lists" — rule #3 — so this is mostly verification, not new code), and
lean on `strength=hard` to carry "he's strict about this set."

**Verify:** after re-ingest, the allowed-verticals set reads as a bounded set in
the facts (not scattered, context-free likes). If it shatters, this is the
deferred sharp edge firing early — note it, don't over-engineer.

---

## Workstream B — Read everything from the graph

Only after A is verified faithful.

### Task B.1 — Rebuild `profile()` to read from the graph

**File:** `brain/brain/service.py` (`profile`)

Replace the `MATCH (e:Episodic) ... RETURN e.content` body-dump with a traversal
of the owner hub: all **current** (non-invalidated: `invalid_at`/`expired_at` IS
NULL) `RELATES_TO` facts with their `polarity`/`strength`. Return a **flat list**
of facts — not prose, not grouped (Decisions #3).

**Proposed shape:**
```json
{ "facts": [ { "fact": "...", "polarity": "negative", "strength": "hard",
               "valid_at": "...", "name": "..." } ] }
```

**Verify:** faithfulness diff against the saved old body-dump — every high-signal
item (TS/SCI, avoid-list, gate-as-hard) present, with correct `strength`.

### Task B.2 — `recall()` returns facts by default; bodies behind a debug flag

**Files:** `brain/brain/service.py` (`recall`), `brain/brain/api.py` (response +
query param + MCP tool docstrings).

Default response: scored facts only (now carrying `polarity`/`strength`). **Drop
`episodes` from the default payload entirely** — a label won't stop an LLM from
reading inlined body text, so the body has to *leave the payload*, not get
relabelled (Decisions #4). Add an explicit, off-by-default debug switch (e.g.
`?debug=true` on HTTP; a `debug` arg on the MCP tool) that re-includes source
bodies/refs for human tracing. Update the docstrings that tell consumers to "read
`episodes` for completeness."

**Verify:** default `recall` has no `episodes`; `?debug=true` does. Recall battery
(`test-brain` skill): on-topic ≫ off-topic; a negative query ("what does the user
avoid") returns avoid-facts from the graph, not from a body.

### Task B.3 — Retire the body-dump rationale in docs/docstrings

**Files:** `brain/brain/service.py` + `brain/brain/api.py` docstrings;
`brain/ARCHITECTURE.md` ("Why recall ALSO returns episode bodies", "Resolved →
blind-spot problem", the Interfaces table); `docs/consumer-api.md` (stale on
`/profile` — scout already flagged it), `docs/memory-model.md`; the PWA `#docs`
section (`pwa/src/docs.ts`, the "Return facts and episodes" / "read episodes for
completeness" copy).

Replace "the graph is lossy so we return bodies" with the new model: the graph is
the source of truth; bodies are debug-only provenance. **Do these *with* the code
(B.1/B.2), not before** — these docs describe current behavior, and `docs/` is
explicitly non-historical, so they must not claim the new contract until it ships.
Add the closing note to `LEARNINGS.md` Chapter 4.

---

## Workstream C — Migrate + verify (the gate)

### Task C.1 — Tweak the Notion source, then wipe + re-ingest

- **Notion tweak (Guardrail #2):** separate *preference strength* ("hard gate —
  out of scope for me") from *scout-app actions* ("no outreach, no tracker
  entry"). The brain ingests the former; the latter belongs in scout.
  *Also correct the data:* per the owner, location is **SF + remote only, held
  hard** (the stored "Bay Area + case-by-case defense exception" overstates it).
- Wipe: `python3 scripts/reset_brain.py --graph brain --force`
- Re-ingest the tweaked doc via `.claude/skills/test-brain/ingest_doc.py`.

**Side effect:** rewrites local graph data only — fully redoable, no external
state.

### Task C.2 — Run the `test-brain` eval flow as the gate

Profile faithfulness (gates present as `strength=hard`? TS/SCI survived? strength
preserved? no conflation?) + recall separation (on-topic vs. control). **This gate
must pass before any consumer relies on graph-only reads — and before Workstream
D.**

---

## Workstream D — Migrate the scout consumer (LAST; separate repo)

**Repo:** `~/Repositories/scout` (Go) — `internal/brainbot/client.go`, plus the
criteria/verdict assembly that consumes it.

**This is not a one-line change, and it must come last.** Scout's criteria block
is built *from episode bodies on purpose* — its own client says *"the
gates/exclusions live in the bodies, NOT the facts — a scorer built off facts
alone will pursue companies the user hard-excludes."* Scout is a living artifact
of the Chapter-3 workaround. Path A moves the gates *into* the facts (as
`polarity=negative`, `strength=hard`); only after that is true can scout read
facts.

Changes when the time comes:
- `Fact` struct gains `polarity` + `strength` (json tags).
- `ProfileResult` becomes `{facts:[...]}`; drop the `Episodes`-as-criteria path
  and the `Bodies()` helpers (or repoint them at the debug flag for tooling only).
- Rebuild the criteria block from facts + `strength` instead of body text.
- Rewrite the now-false comments (lines ~60–99: "facts are a lossy POSITIVE-ONLY
  index", "read Episode bodies instead").

**Ordering safety:** if the brain ships B before scout is updated, scout's body
reads simply return empty → it falls back to **local `taste.md` criteria** (the
brain is "an enhancement, never a hard dependency"). So brain-first degrades scout
gracefully; it does not break it. Doing scout *first* is the dangerous order (it
would score against gate-less facts).

---

## Sequencing

```
A.1 negatives ─┐
A.2 typed edge ┤─► re-ingest + VERIFY graph faithful (C.1, partial C.2)
A.3 closed-set ┘            │
                            ▼
   B.1 profile ─► B.2 recall ─► B.3 docs(+with-code)
                            │
                            ▼
                    full C.2 eval GATE  ──►  D. scout migration (separate repo)
```

Make the graph faithful → **prove it** → flip the brain reads → *then* migrate the
consumer. Each arrow is a real dependency, not a preference.

## Blast radius (who changes, who doesn't)

| Surface | Change |
|---|---|
| Claude Code hook (`inject_memory.py`) | **none** — already reads only `facts` |
| `brainbot` typed client `BrainClient.recall()` | **none** — reads only `facts` |
| `brainbot` typed client `BrainClient.profile()` | one line: `.get("episodes")` → `.get("facts")` |
| Scout (`~/Repositories/scout`) | **real change, Workstream D** — body-dependent by design |
| PWA `#docs` text | content update (B.3) — it *describes* the old model |
| PWA capture path | **none** — `/capture` untouched |

No consumer changes *how it calls* the brain. Recall — the path the scout actually
scores on — is additive (drop an ignored field, add two new ones).

## Out of scope / unchanged

- **Scale assumptions hold.** Still single-domain (career), still
  "dump-everything fits in context." This changes *where* the dump comes from
  (graph, not bodies), not the broad-retrieval strategy.
- **Episodes keep being stored.** Still the provenance/audit record and the
  re-extraction source — we just stop *reading knowledge out of* them by default.
- **No dependency, no infra change.** Same graphiti, same FalkorDB.

## Decisions (settled in design review)

1. **Edge modeling** — single generic `Asserts{polarity,strength}` edge. The fact
   text carries the verb; we don't name edges per domain. ✅
2. **Rules representation** — **no `Constraint` nodes.** Gates/exceptions/
   precedence are the consumer LLM's reasoning over `strength`-tagged facts, not
   brain structure. Everything is a fact. ✅
3. **`profile()` output** — flat fact list (not grouped). ✅
4. **`recall()` bodies** — dropped from the default payload; available only behind
   an explicit debug flag. (Not "keep + relabel" — a label can't stop an LLM
   reading inlined text.) ✅

## Deferred sharp edges (revisit only if they bite)

- **Exact closed-set fidelity.** We rely on the LLM reading a `strength=hard`
  set-membership fact and inferring "outside the set → excluded." If scout ever
  misfires on an *unlisted* item (treats a never-mentioned vertical as allowed),
  that's this edge firing — then we make set-closedness explicit. Not before.
