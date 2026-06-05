# Plan: recall precision — section chunking + relevance-threshold retrieval

## Status: shipped (with one correction; brain-side, consumer-agnostic)

- Proposal 1 (section chunking) shipped as specced — `0debf46`.
- Proposal 2 shipped CORRECTED — `7acb531`: the consumer-supplied `min_score`
  below was rejected as a librarian-boundary violation (a raw RRF cutoff makes
  consumers learn brain internals; and RRF is rank-only, so it carries no
  relevance magnitude to threshold anyway). Replaced by `complete=true`: the
  brain trims the semantic arm at its own relative cosine-sim floor
  (`_COMPLETE_SIM_FLOOR`) before fusion, k kept as a safety cap. Consumers
  state intent; only the brain tunes its internals.
- Proposal 3 (`focus` on recall) not built.
- Verified 2026-06-04 by live A/B on scout's 4 real questions after re-ingest:
  whole-page recall returned all 3 pages flat (~0.016) for every question;
  sections + complete returned question-specific sets (dealbreakers → exactly
  the 🚫 sections at 15% of the chars; stage → one section at 7%).

## Context / problem

The brain is a pgvector document substrate; `recall(q, k)` returns the top-k most
relevant **chunks**. Today a chunk is a **whole page** (Phase-1 "whole page = one
chunk"). With a real corpus that has two consequences for **every** consumer, not
just scout:

- **Recall can't discriminate within a page.** A query about topic A returns the
  whole page that also covers unrelated topic B, scored almost flat. (Observed
  live: a 3-page corpus returns all 3 pages at ~0.0164 — undifferentiated.)
- **Consumers reinvent client-side focusing.** Because recall hands back the
  irrelevant majority of a page, each consumer has to filter/triage it. Scout had
  to add a whole classify-then-synthesize LLM step *purely to compensate* — to
  throw away the parts of returned pages that don't bear on its question.
- **top-k is blunt.** The right number of relevant chunks is unknown per query; k
  too small misses a criterion, k too large floods the consumer with noise.

This is a brain-layer deficiency. Fixing it helps all consumers and shrinks the
focusing burden each one currently reinvents.

## Design principles (non-negotiable)

This layer sits between the brain and **all** consumers, so:

- **Consumer-agnostic.** No consumer's domain may enter the brain — no "company",
  no "role", no scout vocabulary. The brain returns content; consumers interpret.
- **Generalized OR neutrally parameterized.** A change is either domain-general
  (helps everyone identically) or exposed as a neutral parameter the consumer
  supplies (e.g. `focus`) — the brain never hardcodes a consumer's intent.
- **Contract-stable.** Keep the recall shape `{chunks:[{heading,text,score,path}]}`.
  Consumers shouldn't need code changes to benefit; results just get sharper.

## Proposal 1 — section-level chunking (ingest-time)  ← foundation

Split each source into **sections** at ingest, by its own structure (Notion
blocks / markdown headers), one chunk per section, each carrying its section
heading + source path. Recall then returns tight sections instead of whole pages.

- General: finer granularity helps every consumer and every query.
- Contract unchanged: still `{heading, text, score, path}` — `heading` becomes the
  section heading, `path` the source path (consider `path/heading` for uniqueness).
- Scores start to **discriminate**: a query about topic A ranks the A-section above
  the B-section of the same page, instead of returning the page flat.

## Proposal 2 — relevance-threshold retrieval mode

Add a mode that returns **all chunks above a relevance threshold**, not just a
fixed top-k — the "return everything related" successor named in
`scout-migration.md`.

- Param: `min_score` (float) and/or `mode=threshold`; keep `k` as a safety cap.
  Neutral and general.
- Lets completeness-sensitive consumers (anything doing hard gating) say "give me
  everything relevant" without guessing k — the missing-a-criterion risk goes away.

## Proposal 3 (optional) — a neutral `focus` param on recall

The profile face already carried a `focus` arg. Expose an optional `focus` string
on `recall` that **re-ranks / biases** retrieval toward an aspect, treated purely
as an additional query signal — the brain never learns what the consumer means by
it. This is the sanctioned escape hatch for consumer-specific shaping that keeps
the brain generic.

## What this buys consumers (scout as the worked example)

- Section chunks + threshold recall mean "what kind of company does the user want"
  returns the relevant **sections** of the right source, not the whole page plus an
  unrelated page.
- Scout's client-side classify-then-synthesize focusing step **shrinks or
  disappears** — the brain does the relevance work it should own. The boundary
  stays clean: scout still writes the interpretation (its fit-brief); the brain
  just returns better-scoped content.
- The same win accrues to any future consumer for free.

## Sequencing / risks

- Proposal 1 is the foundation; 2 and 3 build on it.
- Re-chunking is a re-ingest (wipe-replace per source) — backfill existing sources.
- Embedding cost scales with chunk count (more, smaller chunks) — modest at this
  corpus size.
- Don't over-split: sub-sentence chunks lose context. Section granularity is the
  target, not maximal fragmentation.

## Verification

- On a multi-topic page, recall ranks the on-topic section above off-topic ones,
  with **separated** scores (not flat ~0.0164).
- A threshold query returns a complete relevant set without a hand-tuned k.
- Existing consumers keep working unchanged (contract shape preserved).
