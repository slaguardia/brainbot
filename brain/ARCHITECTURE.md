# Brain Architecture

> Living design doc. Point at this during design discussions. Implementation
> details (how to run, config, deps) live in [`README.md`](./README.md); this
> is the *why* and the *shape*.

## What the brain is

A **central knowledge hub for a suite of personal apps.** It is a
domain-agnostic factual oracle about **one user**. It knows things about the
user; it does not know what any app *does* with that knowledge.

Job-fit ("scout") is the first consumer. Others will follow (reading triage,
calendar prep, etc.). The brain must never learn what a "job" is — that's what
lets it serve all of them.

## The three-layer model

```
┌──────────────────────────────────────────────────────────────┐
│ APP  (scout, …)                                                │
│   common intelligence library:   TASK  →  questions            │
│     "to judge this company I need: target verticals? stage?    │
│      location? dealbreakers?"                                   │
│   app agent:   facts → reasoning → DECISION                     │
│     synthesizes the facts, applies gates, weighs the rest →    │
│     pursue / skip / maybe                                       │
└───────────────┬───────────────────────────▲──────────────────┘
                │ questions (as queries)      │ relevant facts
                ▼                             │
┌──────────────────────────────────────────────────────────────┐
│ BRAIN  (this service)                                          │
│   QUESTION  →  relevant facts    (librarian: no synthesis)     │
│     "what stage does the user prefer?"                         │
│       → facts: "prefers pre-seed–Series A", "avoids Series C+" │
└───────────────┬───────────────────────────▲──────────────────┘
                │ add_episode                 │ search
                ▼                             │
┌──────────────────────────────────────────────────────────────┐
│ graphiti-core (imported directly)  →  FalkorDB                 │
│   extraction · dedup · bi-temporal facts · hybrid search       │
└──────────────────────────────────────────────────────────────┘
```

**Division of responsibility:**
- **App's intelligence library** — turns a *task* into the *questions* it needs answered, and owns the *cutoff* on the brain's scored results (how confident / how many facts to trust for this task). Reusable across apps; concrete shape is still TBD and lives app-side, not here.
- **Brain** — returns the *facts relevant to a question*. It is a **librarian**: no synthesis, no inference, no decisions. It can never reason wrong because it never reasons.
- **App agent** — synthesizes the returned facts and turns them into a *decision*. Owns all reasoning and task/domain logic (e.g. which answers are gates vs weights, whether a 200-person company is "too big").

Line in one sentence: **the brain hands back what it knows; the app reasons and decides.**

## Interfaces

| Operation | Status | Shape | Notes |
|---|---|---|---|
| `capture(text)` | built | text → **one** episode | LLM **rewrite** (faithful, rule-preserving, named-subject prose) → a single `add_episode` with extraction tuning. No per-fact fan-out. |
| `recall(query)` | built | question → scored `facts` | scored entity-edges, each carrying `polarity` (positive/negative) and `strength` (hard/soft) — negatives and gates are facts now, so the facts are complete. Episode bodies are returned **only** behind `debug=true`: provenance for human tracing, not a knowledge surface. |
| `profile()` | built | → flat list of current `facts` | every current fact, each with `polarity`/`strength` — not episode bodies. The blind-spot fix + the negatives/policies fix. `GET /profile`, MCP `profile`. |

Decision (settled): **there is no `ask` method.** Because the brain is a librarian (no synthesis), "ask the brain a question" *is* `recall` — the app sends its question as the query and reasons over the facts itself. A synthesizing `ask` would have pulled reasoning into the brain, which we explicitly don't want.

Two faces, one service: HTTP (`/capture`, `/recall`) for apps, MCP (`/mcp`) for Claude Code.

### Retrieval contract (decided)

`recall(query)` returns each fact **with an absolute "on-target" relevance score** (a similarity, not a relative rank). What that buys, and where the line sits:

- **Brain reports; it does not threshold.** It returns the facts and how on-target each is. It does NOT decide "how many is enough" or "is this strong enough to count" — that's a judgment.
- **The cutoff is the app's job**, because the right cutoff is *task-dependent* and only the app knows the task:
  - *gate* questions ("is fintech a target vertical?") want **high precision** — trust only confident hits.
  - *profile* questions ("what does the user value?") want **high recall** — take everything plausible.
- **"The brain knows nothing" falls out for free:** if every returned fact scores low, the app concludes the brain is grasping. No separate "I don't know" mechanism needed.

Scores are computed as absolute cosine(query embedding, fact embedding) — `search_` strips `fact_embedding`, so we fetch it per candidate and compute it ourselves. The thresholding that consumes these scores lives in the **app's intelligence library** — app-side, not the brain's concern.

### How we got here: graph as the single source of truth (historical note)

The graph is the **single source of truth**; reads come from facts. It wasn't always so. We briefly returned episode bodies because graphiti's extractor only pulled positive entity-facts ("targets X", "accepts Y") and dropped negatives and policies ("avoids Z", "hard gate: anything outside the set is a skip") — proven on the real target-role doc, where the avoid-list and the vertical gate survived in the episode **body** but never became edges. Returning bodies patched the symptom but quietly made the *text* the source of truth, bypassing the graph.

**Path A** fixed the cause instead: extraction now captures negatives and gates as first-class facts, each carrying `polarity` (positive/negative) and `strength` (hard/soft). So "avoids X", "excludes Y", and hard gates *are* facts. With the facts complete, reads come from the graph again — `recall` and `profile` return facts, and episode bodies surface only as `debug=true` provenance. The graph still earns its keep on dedup, bi-temporal, scored lookups, and future relational queries. Full timeline in [`../LEARNINGS.md`](../LEARNINGS.md) Ch 3–4.

## How the brain works internally (current)

- **Capture:** raw text → LLM decomposer (named-subject rewrite + atomic facts) → `add_episode` per fact, with `custom_extraction_instructions` that override graphiti's "never extract abstract concepts" default. `BRAIN_USER_NAME` binds first-person ("I") to the user.
- **Storage:** graphiti-core called directly (not via an MCP server) over FalkorDB. We keep graphiti for **entity dedup** and **bi-temporal fact invalidation** — the two hardest things to rebuild and the project's real differentiators.
- **Recall:** hybrid edge search (RRF) → facts.

## Data model: episodes, facts, and the two hubs

The brain stores two kinds of thing and links them with two kinds of edge:

- **Episodes** — each capture becomes one episode holding the faithful rewritten text. Stored as **provenance**: the audit trail and re-extraction source. Still kept, but **not** the returned knowledge surface — consumers read facts.
- **Facts** — structured `subject → relationship → object` claims the extractor pulls out of episodes, each carrying `polarity`/`strength`. The **source of truth** for reads (negatives and gates included).

Two edge types connect them, which produces **two natural hubs** in the graph:

| Edge | Direction | Meaning | Hub it creates |
|---|---|---|---|
| `MENTIONS` | episode → entity | **provenance** — which capture a thing came from | the episode node (links to everything it produced) |
| `RELATES_TO` | entity → entity | **knowledge** — the facts themselves | the owner node (subject of most facts) |

So the graph typically shows two well-connected hubs: the most recent capture (its episode) and the owner. **This is by design, not clutter:**

- The **episode hub** is the *provenance index* — trace any fact back to the capture it came from, and fetch the complete faithful body for human auditing or re-extraction (exposed only via `debug=true`).
- The **owner hub** is the *knowledge index* — the web of what's true about the owner.

As more is captured, each capture adds its own episode hub, and an entity that appears in several captures bridges those episodes — which is how the brain corroborates a fact across multiple sources. This brain is **single-user by design**, so the owner remaining a central hub is expected and correct, not a scaling problem.

## Scope discipline (what we are deliberately NOT doing yet)

- **No domain separation.** With one use case (career), there's no cross-domain bleed to engineer around. Domains (tags, nodes, communities) are deferred until a second use case forces the question.
- **No retrieval-ranking optimization.** At one-user / one-domain scale, the whole relevant profile fits in an LLM's context — retrieve broadly and let synthesis reason, rather than tuning rerankers. Ranking optimization is a scale problem we don't have.
- **No multi-tenant.** Single user (`BRAIN_USER_NAME`). Multi-human-per-brain would be a per-identity rewrite, out of scope.

## Settled principles

1. **graphiti-core direct, not via the MCP server.** The MCP wrapper hid the controls a personal brain needs (extraction override, search recipes). graphiti-core exposes all of it.
2. **Keep graphiti; don't go raw FalkorDB.** Dedup + bi-temporal are worth keeping.
3. **At this scale, retrieve broadly; let synthesis reason.** Don't optimize ranking prematurely.
4. **Capture fidelity = preserve strength, not decisions.** The brain should record *how strongly* the user holds something (dealbreaker vs nice-to-have) because that's a fact about them. It must NOT encode app decisions (what to do with a gate).
5. **Decisions live in apps; facts live in the brain.**
6. **The brain never synthesizes or reasons — librarian only.** "Ask the brain" = `recall`. All synthesis/inference is the app agent's job.

## Implementation plan (current build)

Two additive changes; everything else (capture, basic recall, both faces) is already built.

**Item 1 — absolute relevance score on `recall`.** graphiti's reranker scores are *relative* (RRF), but edges carry a queryable `fact_embedding`, so we compute the absolute "on-target" score ourselves:
1. Verify whether `search_` returns `fact_embedding` populated. Path A (populated) → use directly; Path B (stripped) → fetch embeddings for result uuids via one Cypher.
2. Embed the query with the brain's Voyage embedder.
3. In `recall()`: after hybrid `search_` (kept for recall breadth), compute `cosine(query_emb, fact_embedding)` per edge → `score` ∈ [0,1]; sort desc; add `score` to each fact.
- Files: `service.py`, `client.py` (expose embedder). Verify: on-topic → high; nothing-known → all low.

**Item 2 — full-profile dump.** A dedicated `profile` op (not overloaded `recall` — "everything" vs "search" are different semantics):
1. `service.py` `profile()`: Cypher `MATCH ()-[r:RELATES_TO]->() WHERE r.group_id=$gid AND r.expired_at IS NULL RETURN fact, name, polarity, strength, valid_at, invalid_at` ordered by `created_at` desc. `expired_at IS NULL` = current facts only (excludes bi-temporally superseded).
2. `api.py`: `GET /profile` + `profile` MCP tool. Same fact shape as recall (with `polarity`/`strength`), no score.
- Verify: returns all current facts, negatives and gates included; superseded ones excluded.

Order: Item 1 (verify de-risks it) then Item 2. Both purely additive.

## Scale cliffs (deliberate short-term choices — revisit later)

Two of our retrieval decisions are **single-domain, small-scale crutches**. They're the right call now and will break on known triggers. Flagged so we revisit deliberately, not by surprise.

- **Full-profile dump assumes one domain + fits-in-context.** It works because the brain is career-only (everything dumped is relevant) and small (fits an LLM context). **Breaks when:** (a) a second domain enters the brain → dumping everything drags the wrong domain into a task → *this is exactly when the deferred domain-separation question returns*; or (b) the profile outgrows the context window.
- **The long-term answer (when the above breaks): retrieve against the task artifact.** Instead of the app pre-forming questions, give the brain the actual artifact (e.g. the company/job posting) and match it against *all* facts — a defense-tech posting then semantically pulls the clearance fact with nobody having to ask. This dissolves the blind-spot *and* scopes to relevance without a domain taxonomy. Strong candidate for the eventual design; not built now.

## Open questions

(None blocking the job-fit v1. The retrieval problems are resolved for current scale; their scale-cliff successors are noted above.)

## Resolved

- **No `ask` method.** Collapsed into `recall` once we settled that the brain is a librarian with no synthesis (see Interfaces).
- **The noise problem (false positives).** The brain returns facts with an absolute on-target relevance score and does **not** threshold; the app's intelligence library owns the task-dependent cutoff. "Brain knows nothing" = all scores low. See *Retrieval contract* above. (Score surfacing decided but unbuilt.)
- **The blind-spot problem (false negatives).** At current scale, solved by **completeness, not cleverness**: extraction now captures negatives and gates as facts (`polarity`/`strength`), and the full-profile dump returns every current fact, so nothing relevant can be missed. Scores can't fix blind spots (you can't rank what was never fetched); dumping everything sidesteps them. See *Scale cliffs* for when this stops working.
