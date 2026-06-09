# Plan: agent-task support — make the brain exceptional for agents informing tasks

## Status: proposed (not started)

## Context / problem

The brain serves a faithful **grounding** read for consumers: `recall` returns
quotable source passages (librarian, not oracle), `doc(id)` + `version` give
deterministic pinning, `map()` + path `scope` + `complete=true` give discovery
and domain-narrowing, and the same reads are exposed over MCP. As the retrieval
floor under an agent's task, this is solid.

It is not yet *exceptional for agents doing tasks*. The three-layer model
(`docs/brain-architecture.md`) already names the target — `TASK → scope/query`
in the app's intelligence library, `context → reasoning → DECISION` in the app
agent — but two of the three things that would deliver it are missing:

- The **app's intelligence library** is a box in a diagram (`scout, …`, separate
  repo). The shipped `web-toolkit/src/brain/index.ts` is thin `recall/doc/map`
  HTTP wrappers. Every new agent re-implements task→query from scratch.
- **Retrieval is single-shot**, query-in/chunks-out. No query decomposition, no
  reranking (deferred in `brain-architecture.md`), no recency/conflict signal.
  `score` is a raw RRF rank the consumer is told to threshold itself.

The one shipped agent integration (the Claude Code `UserPromptSubmit` hook) is
the weakest expression of the vision: one `recall` over the raw prompt,
prepended — ambient injection, not an agent driving retrieval to do a task.

This is a holding doc for three directions worth pursuing later. A and B stay
inside settled decisions and live on the read path. C (write-back) is what
closes the loop — it adds the *accumulation* axis the read directions
structurally cannot — and it reopens two settled decisions, so it carries its
own design constraints below.

## Direction A — app-side intelligence library (toolkit)

Build the reusable layer the docs already promise: a toolkit module that turns
an app's *task* into multi-query retrieval and ranks/handles the results, so
each new agent doesn't re-derive it.

- Lives **above** the brain (in `web-toolkit` and/or an agent-side helper), not
  in the brain. No brain changes; fully consistent with every settled decision.
- Candidate surface: task → fan-out of `recall` queries + `scope` selection →
  dedup/merge chunks by owning `doc` id → optional `doc()` escalation for pinned
  grounding → a ranked, deduped `Context` the app agent reasons over.
- The librarian boundary holds: this layer *consumes* faithful content and does
  the reasoning; it never asks the brain to synthesize.

## Direction B — task-aware retrieval inside the brain

Make `recall` itself stronger for task-shaped queries, while staying a
librarian (retrieve + arrange faithful content, never synthesize/decide).

- Candidate moves: query decomposition before fan-out, a rerank pass over the
  RRF candidate set, and recency/conflict signals surfaced on results (so an
  agent can see "this fact is stale / contradicted elsewhere" instead of a bare
  rank score).
- Touches *soft* deferrals (reranking, query transforms were "not yet," not
  "never") — not the hard non-goals. Read path stays LLM-free where the existing
  docs require it; any LLM use here would need its own sign-off against that
  invariant.

## Direction C — write-back / closed learning loop

Let agents deposit what they learn back into the brain, so tasks accumulate
truth over time instead of only hand-curated Notion edits doing so. This is the
highest-leverage direction *and* the one with the most design risk, because it
reopens two settled lines — `docs/brain.md`/`brain-architecture.md`: *"There is
no `capture`"*, and `docs/consumer-integration.md`: *"Writes come only from
sources."* Pursuing C amends those docs; it does not work around them.

Design constraints (settled in discussion 2026-06-09):

- **Clean separation is mandatory, not tidiness.** Agent-written data must be
  distinguishable from Notion-ingested sources at read time, always. Two reasons
  it's load-bearing: (1) it protects the *canonical* invariant — without it an
  agent grounds tomorrow's decision on yesterday's agent guess, a compounding
  feedback loop; (2) lifecycles differ — Notion sources have wipe-replace
  currency and an "edit the page → re-sync" mutation path; agent writes have no
  page behind them and are append-mostly observations with their own staleness.

- **The brain enforces the tier; the SDK is the ergonomic front door.** The
  toolkit *exposes* the write, but separation cannot be SDK convention — the
  first consumer that calls the raw endpoint (or a buggy one) would pollute the
  canonical corpus. Discipline lives server-side, same shape as today's read
  proxy.

- **Narrow scope: agent-observed facts *about the user*, cross-app and
  reusable.** App *working set* (scout's verdicts, a reader's read/unread) stays
  in the app's own store — the existing docs already split this correctly, and C
  must not become a dump for working-set or it breaks that separation. Only
  brain-shaped, agent-origin user facts ("had coffee with X", "declined three
  onsite roles → leans remote") are write-back candidates.

- **Second-class tier with provenance and a promotion path.** Agent writes are
  explicitly lower-trust: `recall` *may* include them but always stamps them
  `agent-origin` with provenance (which agent, when, derived-from). A confirmed
  agent fact can graduate into a real Notion source. This keeps "sources are
  canonical" *true* — agent claims never silently become canon.

- **Open fork: how to separate.** Start with an origin/`kind` tag in the
  existing `sources`/`chunks` tables (the `kind` column already exists; recall
  filters/weights by origin); split into a separate captures store only if the
  lifecycles diverge enough to warrant it. Path-namespace convention is the
  cheap third option but is convention, not an enforced wall.

## Notes

- Saved as a future-work capture, not a committed roadmap. No success criteria
  or implementation sketch yet — flesh out per-direction when picked up.
- Both A and B preserve "the brain hands back what it knows; the app reasons and
  decides." Neither introduces an `ask`/synthesis endpoint.
