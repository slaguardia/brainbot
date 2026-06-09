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

This is a holding doc for two directions worth pursuing later. Both stay inside
settled decisions. A third direction (write-back) is explicitly parked below.

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

## Parked — write-back / closed learning loop (not now)

Letting agents deposit task output back into the brain (scout's verdicts, "had
coffee with X") would close the loop and is the highest-leverage idea, but it
**directly contradicts a settled decision** — `docs/consumer-integration.md`:
*"Writes come only from sources."* Decided 2026-06-09 to leave this out for now;
revisit only as a deliberate architectural call, not folded into A or B.

## Notes

- Saved as a future-work capture, not a committed roadmap. No success criteria
  or implementation sketch yet — flesh out per-direction when picked up.
- Both A and B preserve "the brain hands back what it knows; the app reasons and
  decides." Neither introduces an `ask`/synthesis endpoint.
