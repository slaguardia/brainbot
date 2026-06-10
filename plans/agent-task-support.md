# Plan: agent-task support — make the brain exceptional for agents informing tasks

## Status: spec (checklist) — A + B active, C shelved (updated 2026-06-09)

> Written as a checklist so it drops into a goal/`execute` run. Design context is
> up top (the *why* a goal-executor needs); the actionable work is the checklists
> below, each item with an observable **verify**. Do phases top-down: B.0 gates
> B.1, B.1 gates B-config. A is independent but benefits from B.

## Context / problem

The brain serves a faithful **grounding** read: `recall` returns quotable source
passages (librarian, not oracle), `doc(id)` + `version` pin deterministically,
`map()` + path `scope` give discovery. As the retrieval floor under an agent's
task this is solid — but retrieval is **single-shot**, query-in/chunks-out: no
query understanding, no multi-pass coverage check, no rerank, no recency/conflict
signal, and `score` is a raw RRF rank the consumer is told to threshold itself.
The one shipped agent integration (the Claude Code `UserPromptSubmit` hook) is the
weakest form of the vision: one `recall` over the raw prompt, prepended.

## Settled decisions (2026-06-09) — the frame for every item below

1. **Brain-side LLM is accepted.** The Phase-1 "LLM-free read path" tenet was a
   floor, not permanent. The goal is the **best mechanical + LLM combination**,
   found by evaluation — not LLM-everywhere, not no-LLM purity.
2. **The librarian boundary HOLDS.** The LLM reasons only about *how/what to
   retrieve* (decompose, multi-pass, rerank, judge recency/conflict). The brain
   still returns **faithful source content**, never synthesizes, never decides.
   **No `ask` endpoint.** The app reasons over the content and decides.
3. **B is the investment, brain-side.** The multi-pass loop lives *in* the brain
   so every consumer gets it free and there is **one surface to evaluate**.
   Direction A shrinks to a thin app-side task-shaping client.
4. **Config follows `docs/configuration-convention.md`.** The chain's prompts are
   owner-configurable (with defaults) via the brain's config surface — never via
   per-call SDK params. Consumers pass intent only.
5. **C (write-back) is shelved** (captured at the bottom; not in scope).

---

## Phase 0 — Design & docs firm-up  *(done this session)*

- [x] A/B spec'd, C shelved — this doc
- [x] `docs/configuration-convention.md` — the owner-config-vs-SDK-wire rule
- [x] `docs/web-toolkit.md` drift fixed — `doc()` return shape corrected; `changes`/`onChange` added
- [x] `.claude/skills/audit-interface-docs/` — the per-repo doc-audit skill
- [ ] scout owner-config doc — **deferred to the scout repo** (no current-truth content to write here yet)

## Phase B.0 — Eval scorecard  *(the honest first build; everything in B gates on it)*

Why first: the only relevant prior result cuts against naive LLM cleverness — a
2026-06-06 A/B found **raw queries beat Haiku-rewritten ones 9/9 vs 7/9 rank-1**
(`project_query_rewrite_parked`). So every B feature must *prove* lift, and that
needs a scorecard before any chain work.

- [ ] **Labelled eval set** — a committed set of `(query → expected source id)`
      pairs spanning the current corpus's domains.
      *verify:* file committed; every expected id resolves in `map()`; ≥1 query per
      domain branch.
- [ ] **recall@k / precision harness** — runs the set against `recall`, prints
      recall@k + MRR.
      *verify:* one command outputs a scorecard table; reruns are deterministic
      (same corpus → same numbers).
- [ ] **Baseline recorded** — single-shot RRF scored and committed as the bar every
      later feature must beat.
      *verify:* baseline scorecard committed next to the harness.

## Phase B.1 — Agentic retrieval chain  *(gated on B.0; each sub-feature gated on measured lift)*

- [ ] **Query understanding** — turn intent into 1+ sub-queries; ship the
      decomposition path **only where it beats raw** on the scorecard.
      *verify:* A/B logged; decomposition enabled only if recall@k ≥ baseline, else
      left off (and that's recorded).
- [ ] **Multi-pass, coverage-judged search** — after each pass an LLM judges
      coverage and may issue a follow-up query; hard pass ceiling.
      *verify:* a multi-facet query retrieves a facet single-shot misses (shown on
      the scorecard); logs show pass count never exceeds the ceiling.
- [ ] **Rerank pass** — reorder the merged candidate set; ship **only on measured
      lift**.
      *verify:* scorecard shows recall@k/precision lift vs baseline; no lift ⇒ not
      enabled (recorded).
- [ ] **Signal annotation (librarian-safe)** — each returned chunk carries
      relevance / recency / conflict signals, **additively** (`Chunk[]` still has
      verbatim `text`; no synthesized prose).
      *verify:* recall response includes the signal fields; a consumer ignoring
      them still works unchanged.
- [ ] **Graceful floor** — the LLM path falls back to single-shot RRF on
      error/timeout.
      *verify:* with the LLM disabled or forced to error, `recall` still returns RRF
      chunks.

Open questions (resolve via B.0, don't pre-decide): does decomposition help on
*this* corpus yet (re-test as corpus grows); rerank choice (Voyage rerank vs local
cross-encoder vs LLM-as-reranker); multi-pass stop criterion + ceiling; cost/latency
budget per recall (recall is human-paced — seconds are fine).

## Phase B-config — owner-configurable chain  *(gated on B.1 existing)*

- [ ] **Chain prompts owner-editable, with shipped defaults** — exposed on the
      brain's config surface per `docs/configuration-convention.md`; zero-config
      works out of the box.
      *verify:* brain runs with no config (uses defaults); editing a prompt in
      settings changes chain behavior on the next recall; consumers still call
      `recall(intent)` with no new params.

## Phase A — thin app-side task-shaping client  *(independent; benefits from B)*

A new module in `web-toolkit`, beside `src/brain/index.ts`'s existing thin client.

- [ ] **Task → intent** — turns an app's task into the intent string(s) handed to
      `recall`.
      *verify:* given a sample scout task, the module returns intent(s); unit test.
- [ ] **Merge/dedup by owning doc id** — collapse chunks that share a `doc` id.
      *verify:* duplicate-doc chunks collapse in the output; test.
- [ ] **`doc()` escalation** — fetch a whole document when the task needs pinned
      grounding.
      *verify:* for a task needing a full doc, the module fetches it via `doc(id)`.
- [ ] **Stays thin** — A does **not** re-implement multi-pass/rerank (that lives in
      B, so it isn't duplicated per consumer).
      *verify:* the module contains no LLM-chain logic; it calls `recall` and
      arranges results.

---

## Shelved — Direction C: write-back / closed learning loop

> Parked 2026-06-09. No checklist; captured for when picked up. C reopens two
> settled lines (`docs/brain.md`: *"There is no `capture`"*; `consumer-integration.md`:
> *"Writes come only from sources"*) and adds the *accumulation* axis A and B
> structurally cannot. Pursuing C amends those docs rather than working around them.

Design constraints (still hold whenever C resumes):

- **Clean separation is mandatory.** Agent-written data must be distinguishable
  from Notion-ingested sources at read time, always — (1) protects the *canonical*
  invariant (else an agent grounds tomorrow's decision on yesterday's agent guess,
  a compounding loop); (2) lifecycles differ (Notion sources have wipe-replace
  currency + an edit→re-sync path; agent writes are append-mostly observations with
  no page behind them).
- **The brain enforces the tier; the SDK is the ergonomic front door.** Separation
  can't be SDK convention — the first consumer to hit the raw endpoint would pollute
  the canonical corpus. Discipline lives server-side.
- **Narrow scope: agent-observed facts *about the user*, cross-app and reusable.**
  App working set (scout's verdicts, a reader's read/unread) stays in the app's own
  store. Only brain-shaped, agent-origin user facts are candidates.
- **Second-class tier with provenance and a promotion path.** Agent writes are
  lower-trust: `recall` *may* include them but always stamps them `agent-origin`
  with provenance (which agent, when, derived-from). A confirmed agent fact can
  graduate into a real Notion source — so "sources are canonical" stays true.
- **Open fork (the real decision): how to separate.** Cheap first step: ship an
  origin/`kind` tag in the existing `sources`/`chunks` tables (`kind` already
  exists), then *watch whether agent-write lifecycles actually diverge from
  Notion-source lifecycles* — split into a separate captures store only if they do.

## Notes

- Both A and B preserve "the brain hands back what it knows; the app reasons and
  decides." Neither introduces an `ask`/synthesis endpoint, even with LLM in play.
- Every B feature is gated on B.0 — nothing ships without measured lift over
  single-shot RRF.
