# Plan: Graph as the single source of truth (Path A)

## Status: planned — not started

Everything leaving the brain as agent-feeding knowledge must come from the
graph. Today it doesn't: `profile()` returns raw episode **bodies**, and
`recall()` returns episode bodies alongside facts, because the extractor drops
negatives and policies (see [`../LEARNINGS.md`](../LEARNINGS.md), Chapter 3).
That body-dump quietly made the captured text the source of truth and
circumvented the database the brain exists to be.

This plan makes the **graph** faithful enough to read from — capturing the
negatives, strength, and rules it currently loses — and then rebuilds the read
paths to source everything from it. It restores the original
[`brain/ARCHITECTURE.md`](../brain/ARCHITECTURE.md) "Item 2" design (profile from
`RELATES_TO` facts), which was abandoned only because the graph wasn't faithful
yet.

## Why this is viable now (verified)

The `graphiti-core` we already run supports the full mechanism:
- `add_episode(..., entity_types=, edge_types=, edge_type_map=, custom_extraction_instructions=)` — we currently pass only `entity_types` + `custom_extraction_instructions`.
- `edge_type_map: dict[(source_label, target_label), [edge_type_names]]` selects which typed relationships are allowed between which entity types.
- Custom edge **attributes are extracted and persisted**: when a matched edge type's Pydantic model has fields, graphiti runs a dedicated `extract_attributes` pass and stores them on the edge (`graphiti_core/utils/maintenance/edge_operations.py`).

So `polarity` + `strength` on a typed edge, and a `Constraint` entity type, are
all expressible with the engine as-is. No dependency bump.

## Definition of done

In the `brain` graph, after re-ingesting the real target-role document:
1. The **avoid-list** is present as graph facts (negatives), not only in the body.
2. The **vertical gate** is represented as a hard constraint *in the graph*
   (a `Constraint` node and/or `strength=hard` facts), not only in the body.
3. `profile()` returns content sourced **entirely from the graph** (current facts
   + their `polarity`/`strength` + constraints). No episode-body dump.
4. `recall()` returns graph facts as its knowledge channel. Episode bodies, if
   returned at all, are labelled **provenance**, not the answer.
5. A faithfulness diff (graph-derived profile vs. the old body-dump) shows
   nothing high-signal lost: TS/SCI clearance, the avoid-list, and the
   gate-as-hard all survive.

---

## Guardrails (do not violate)

These are the constraints that make this a *good* implementation, not just a
working one. They come from existing settled principles.

- **Generic, no schema lock-in** (`docs/genericity-rule.md`; `config.py` entity-types comment).
  No career-specific edge types (`Targets`, `Avoids`, …). Use **domain-agnostic
  dimensions** — `polarity` (positive/negative) and `strength` (hard/soft) —
  that apply to health, relationships, money, anything. A `Constraint` entity
  type is generic (every domain has rules); a `JobPreference` type is not.

- **Preserve strength, not decisions** (`brain/ARCHITECTURE.md` principle #4).
  Record *how strongly* the user holds something (dealbreaker vs. nice-to-have).
  Do **not** encode what an app should *do* about it. Concretely: the current
  source text says a gate triggers "an automatic skip with no outreach and no
  tracker entry" — *"outreach" and "tracker" are scout-app actions leaking into
  the brain.* The graph should capture `strength=hard` / a `Constraint`, and the
  app decides what skipping means. (This is also a Notion-source tweak — see
  Workstream C.)

- **Librarian, not synthesizer** (`brain/ARCHITECTURE.md` principle #6).
  `profile()` returns structured facts from the graph, not LLM-synthesized prose.
  The fact strings are already natural language ("Steve LaGuardia avoids
  fintech"); the consumer's LLM reasons over them.

- **Surgical** (`CLAUDE.md` §3). The body-dump rationale is woven through several
  docstrings and docs. Update the ones this change falsifies; don't refactor
  adjacent code.

---

## Workstream A — Make the graph faithful

Sequenced first. Do not touch the read paths (Workstream B) until A is verified,
or you reintroduce the blind spot under a new name.

### Task A.1 — Extract negatives and avoidances

**File:** `brain/brain/config.py` (`DEFAULT_EXTRACTION_INSTRUCTIONS`)

The override currently pushes for concepts/values/goals but says nothing about
*negative* relationships. Add an instruction (generic, any domain) to extract
avoidances, rejections, exclusions, and dislikes as first-class facts — e.g.
"the owner avoids/rejects/will-not X" is exactly as important to record as "the
owner seeks X." Keep it polarity-neutral in wording (not career-specific).

**Verify:** re-ingest the target-role doc (Workstream C), then query the graph:
negatives like "avoids fintech," "avoids pure coding roles," "skips onsite/hybrid
outside the Bay Area" appear as `RELATES_TO` facts. (Before: absent.)

### Task A.2 — Typed edges carrying `polarity` + `strength`

**Files:** `brain/brain/client.py` (define edge types + map, expose them),
`brain/brain/service.py` (`_add` passes `edge_types` + `edge_type_map`).

Define a small, **generic** typed edge with attributes the extractor fills:

```python
class Asserts(BaseModel):
    """A stance the owner holds about a topic/thing the brain should remember."""
    polarity: str  # "positive" (seeks/values/accepts) | "negative" (avoids/rejects)
    strength: str  # "hard" (dealbreaker/gate/requirement) | "soft" (preference)
```

Map it broadly so it applies across domains, e.g.
`{("Entity", "Entity"): ["Asserts"]}` (or the specific owner→topic pairs). The
relationship *verb* still lives in the edge's `fact` string; the attributes add
the two dimensions the body-dump was covering for.

**Verify:** query an edge's `attributes`; confirm `strength`/`polarity` populated.
The vertical gate's facts carry `strength=hard`; a mild preference carries
`strength=soft`.

> **Decision to confirm:** one generic `Asserts` edge (max genericity, fact text
> carries the verb) vs. a few generic named edges (`Seeks`/`Avoids`/`Requires`,
> more directly queryable, slightly more structure). Recommended: start with the
> single generic edge; split only if querying needs it.

### Task A.3 — `Constraint` entity type for if-then rules

**File:** `brain/brain/config.py` (`DEFAULT_ENTITY_TYPES`), instructions note.

Add a generic `Constraint` (a.k.a. rule/policy) entity type: "A rule, gate, or
policy the owner applies — a condition with consequences, not a simple fact."
The gate ("treat the allowed verticals as a gate, not a weight; anything outside
is out") becomes a `Constraint` node linked to the relevant topics, so the rule
**lives in the graph** rather than only in prose.

**Verify:** after re-ingest, a `Constraint` node exists for the vertical gate and
links to the vertical topics. The rule is queryable, not just narratable.

---

## Workstream B — Read everything from the graph

Only after A is verified faithful.

### Task B.1 — Rebuild `profile()` to read from the graph

**File:** `brain/brain/service.py` (`profile`)

Replace the `MATCH (e:Episodic) ... RETURN e.content` body-dump with a traversal
of the owner hub: all **current** (non-invalidated: `invalid_at`/`expired_at` IS
NULL) `RELATES_TO` facts with their `polarity`/`strength` attributes, plus all
`Constraint` nodes. Return structured facts + constraints — not prose.

**Proposed shape:**
```json
{ "facts": [ { "fact": "...", "polarity": "negative", "strength": "hard",
               "valid_at": "...", "name": "..." } ],
  "constraints": [ { "rule": "...", "applies_to": ["..."] } ] }
```

**Verify:** faithfulness diff against the saved old body-dump output — every
high-signal item (TS/SCI, avoid-list, gate-as-hard) is present.

### Task B.2 — Make `recall()`'s knowledge channel the graph

**Files:** `brain/brain/service.py` (`recall`), `brain/brain/api.py` (response +
MCP tool docstrings).

Keep scored facts (now carrying `polarity`/`strength`). The `episodes` body field
stops being the completeness crutch — either drop it or relabel it `provenance`
(source bodies for tracing a fact back to its capture), explicitly not the
answer. Update the tool docstrings that currently tell consumers to "read
`episodes` for completeness."

**Verify:** recall battery (`test-brain` skill) — on-topic ≫ off-topic control;
and a negative query ("what does the user avoid") now returns avoid-facts from
the graph, not from a body.

### Task B.3 — Retire the body-dump rationale in docs/docstrings

**Files:** `brain/brain/service.py` + `brain/brain/api.py` docstrings;
`brain/ARCHITECTURE.md` ("Why recall ALSO returns episode bodies", "Resolved →
blind-spot problem"); `docs/consumer-api.md` / `docs/memory-model.md` where they
state "graph is a lossy positive-only index, we return bodies."

Replace "the graph is lossy so we return bodies" with the new model: the graph is
the source of truth; episodes are provenance. Surgical edits to the falsified
claims only. Add the closing note to `LEARNINGS.md` Chapter 4 when done.

---

## Workstream C — Migrate + verify (gate before trusting it)

### Task C.1 — Tweak the Notion source, then wipe + re-ingest

The graph extracted under the old config is stale. Re-ingest under the new one.

- **Notion tweak (per Guardrail #2):** in the source page, separate the user's
  *preference strength* ("hard gate — out of scope") from *scout-app actions*
  ("no outreach, no tracker entry"). The brain should ingest the former; the
  latter belongs in the scout app, not the brain.
- Wipe: `python3 scripts/reset_brain.py --graph brain --force`
- Re-ingest the (tweaked) target-role doc via `.claude/skills/test-brain/ingest_doc.py`.

**Side effect note:** this only rewrites local graph data — fully redoable, no
external/shared state. Survives `git revert` only as data, not code.

### Task C.2 — Run the `test-brain` eval flow as the gate

Use the existing skill's eval flow: profile faithfulness check (gates present?
TS/SCI survived? strength preserved? no conflation?) + recall separation
(on-topic vs. control). This is the gate that says Path A actually worked before
any consumer relies on the graph-only reads.

---

## Sequencing

```
A.1 negatives ─┐
A.2 typed edges ├─► re-ingest + VERIFY graph faithful (C.1, partial C.2)
A.3 constraints ┘            │
                             ▼
            B.1 profile  ─►  B.2 recall  ─►  B.3 docs
                             │
                             ▼
                       full C.2 eval gate
```

Make the graph faithful, **prove it**, then flip the reads. Flipping before
proving just relocates the blind spot.

## Out of scope / unchanged

- **Scale assumptions hold.** Still single-domain (career), still
  "dump-everything fits in context." This plan changes *where* the dump comes
  from (graph, not bodies), not the broad-retrieval strategy. The domain-separation
  scale-cliff (`brain/ARCHITECTURE.md`) is untouched.
- **Episodes keep being stored.** They remain the provenance/audit record and the
  re-extraction source — we just stop *reading knowledge out of* them.
- **No dependency, no infra change.** Same graphiti, same FalkorDB.

## Open decisions to confirm before building

1. **Edge modeling** — single generic `Asserts` (recommended) vs. a few generic
   named edges. (Task A.2.)
2. **Rules representation** — `Constraint` nodes (recommended) vs. encoding gates
   purely as `strength=hard` facts (simpler, but loses standalone if-then rules).
   (Task A.3.)
3. **`profile()` output** — flat fact list (recommended) vs. grouped by
   topic/polarity. (Task B.1.)
4. **`recall()` episodes field** — drop entirely vs. keep relabelled as
   `provenance` (recommended: keep, relabelled). (Task B.2.)
