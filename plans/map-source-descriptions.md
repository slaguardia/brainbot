# Plan: map source descriptions — a when-to-use signal for consumer routing

## Status: proposed (not started)

## Context / problem

Consumers discover sources through `/map`, which returns `{id, title, path,
parent_id, version}` per source. Title + path is the only routing signal —
fine for navigation, thin for deciding *which document to pin or fetch* for a
job. A consumer choosing between sources must guess from titles or burn a
`/doc` round-trip per candidate to learn what a page actually is.

Meanwhile the curate-notion skill establishes **purpose preambles** as a
content convention: 1–3 keyword-dense lines under the page title saying what
the page is. Today that preamble is consumed only as an embedded chunk (it
recalls when a query asks about the page's subject as a whole, and it leads
`profile()` assembly). As *discovery metadata* it is invisible: nothing reads
it as a when-to-use descriptor (asked and confirmed 2026-06-06).

This plan closes that gap: sources get skill-style descriptions for consumer
routing, derived from content the human already writes.

## Design principles (non-negotiable)

- **One source of truth, human-authored.** The description IS the page's
  preamble first line. No second authoring surface, no parallel field to
  drift: edit the page → re-sync → description updates. The capture = edit =
  re-sync invariant holds untouched.
- **Derived mechanically, no LLM.** The read path stays LLM-free (reaffirmed
  by the query-rewrite A/B, 2026-06-06). Truncation, never summarization —
  the brain serves raw faithful text, not paraphrase.
- **Uniform and consumer-agnostic.** Every source gets the same field by the
  same rule. No length/format knobs for consumers (librarian boundary:
  consumers state intent, never tune brain internals). Designed for any brain
  deployment, not shaped around any one consumer.

## Proposal

1. **Contract.** `/map` items (HTTP and the MCP `map` tool) gain
   `description: str`, `''` when the page has no preamble. `recall`, `doc`,
   and `profile` are unchanged.

2. **Derivation rule.** The first non-empty line of the text *before* the
   first heading line (the preamble), skipping lines that are only a
   `[[ref]]` (hub link rows aren't descriptions); truncated at a word
   boundary to ≤200 chars. Heading-first pages → `''`.
   - First *line*, not the whole preamble: hub pages legitimately carry link
     lists after the purpose line, and content pages may carry their real
     substance in the preamble — the description is a routing hint, not the
     content.
   - No fallback to the first section heading when empty: `''` is signal
     (the page lacks a preamble; curate-notion fixes the page, the brain
     doesn't paper over it).

3. **Implementation sketch** (read-time derivation, no schema change, no
   backfill — same philosophy as `_VERSION_SQL`):
   - `store.map_()`: SELECT adds `left(s.raw_text, 1000) AS head`; a small
     pure helper (reusing `_HEADING_RE`) scans `head` for the preamble first
     line and truncates. Map result sets are small; the 1KB head slice keeps
     the query light.
   - `api.py`: pass `description` through on `/map` and the MCP `map` tool.
     The PWA proxy is already pass-through — no change.

4. **Consumers** (separate, optional, not required by this plan): scout's
   `/map` discovery can read descriptions before pinning; the PWA source map
   can render them as subtitles.

5. **curate-notion synergy** (after shipping): one line added to the skill's
   purpose-preamble checklist item — the first preamble line doubles as the
   source's `/map` description — making the convention doubly load-bearing
   (recall landing chunk + routing metadata).

## Verification

- **Unit**: derivation across preamble page, heading-first page, hub page
  whose preamble is purpose-line + `[[refs]]`, empty page, >200-char first
  line (word-boundary truncation), and NUL-stripped input.
- **Smoke**: `scripts/smoke_substrate.py` asserts `description` present and
  the `''` case.
- **Live eval** on the seeded corpus: `Job Hunting` → its purpose line;
  `Target company` → its Stage/gates line; any heading-first page → `''`.
- **Docs**: `brain/README.md` interface table, `brain/ARCHITECTURE.md` note,
  and the test-brain skill's `/map` row.

## Non-goals

- LLM-generated summaries, or embedding the description separately.
- A dedicated description property in Notion or a PWA editing field.
- Per-consumer description formats or length knobs.
- Changes to `/doc`, `/recall`, or `/profile` contracts.

## Open questions

- Length cap: 200 chars (lean) vs 280. Routing hint, not an abstract.
- Whether `version` should be documented as also covering the description
  (it already does implicitly — description derives from `raw_text`, which
  the version hash covers).
