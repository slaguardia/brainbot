---
name: curate-notion
description: Edit and reorganize the user's Notion pages so they chunk and recall well in the brain — restructure headings into self-describing sections, dedupe facts that live on multiple pages, simplify prose, tune titles/hierarchy for scoping, then re-ingest and verify recall. Use when asked to optimize, clean up, reorganize, or dedupe Notion content for the brain.
---

# Curating Notion for the brain

The brain ingests Notion pages and splits them into **one chunk per heading
section** (`brain/brain/store.py`, `_split_sections`). Recall quality is
therefore mostly determined by how pages are written: heading structure, one
topic per section, one home per fact. This skill is how to edit the Notion
workspace itself — with the user's approval, via the Notion MCP tools — so the
source material retrieves well. Design context: `brain/ARCHITECTURE.md`.

This skill EDITS THE USER'S PERSONAL NOTES. Every write is plan-first,
approval-gated, and verified by re-ingest + recall probes. See Safety rules.

## How a page becomes chunks (the model behind every edit)

From `store.py` + `notion.py` — verify there if a result is surprising:

- **One chunk per markdown heading section.** Notion h1–h3 become `#`–`###`;
  each heading line starts a new chunk: `(heading, body)`.
- **Embed input is `heading\nbody` only — the page title is NOT injected**
  (deliberate: a shared title would pull a page's sections together in vector
  space). So the section heading carries all the retrieval signal for its body.
- **Preamble** (content above the first heading) becomes a chunk whose heading
  is the page title. A page with **no headings is one whole-page chunk** — the
  main failure mode this skill exists to fix.
- **Heading-only sections are kept** (the heading is signal, but a chunk with
  no body recalls weakly). Empty preambles are dropped.
- **What the flattener keeps/drops**: child pages/databases → a `[[title]]`
  reference line only (their content is a separate source); inline link URLs
  are stripped (prompt-injection guard — do NOT carry meaning in links); media
  → caption only; tables → `|`-joined rows; toggles/callouts → flattened text.
- **Hierarchy = `path`, not embeddings.** Ancestor page titles become the
  `path` (`Career/Job Search/Target Role`), used for `scope=` filtering,
  `profile(scope)` assembly, and display. Moving or renaming pages changes
  scoping and navigation, never similarity scores (except the title doubling
  as the preamble chunk's heading).
- **Re-ingest is wipe-replace per source** — edit the page, `POST /ingest` its
  URL, chunks are fully re-derived. Idempotent.
- **Recall is hybrid** cosine + full-text, RRF-fused. Verbatim duplicate prose
  across pages gets found by BOTH halves — dupes actively split and pollute
  results.

## What "optimized" means (the editing checklist)

Audit each page in scope against these, in priority order:

1. **Self-describing headings.** Each heading must identify its body's topic
   standing alone — it's the strongest term in the embed input. `Notes`,
   `Misc`, `Thoughts`, `More` are dead chunks. Rewrite to what the section is
   *about* ("Salary expectations and floor", not "Numbers").
2. **One topic per section.** A section mixing two concerns ranks for neither.
   Split it under two headings. Conversely, merge fragmented one-liner
   sections about the same topic.
3. **Sectionless walls of text.** Any page > ~1 screen with no headings is one
   flat chunk. Impose heading structure from its own content.
4. **One canonical home per fact (dedupe).** When the same fact lives on
   multiple pages, pick the canonical page (best `path` fit, most complete
   treatment), keep it there, and on the other pages delete the duplicate and
   leave a one-line plain-text pointer naming the canonical page title (e.g.
   "Salary details live in [[Compensation]]"). Title mentions survive ingest
   as searchable text; inline URLs don't.
5. **Purpose preamble.** 1–3 plain lines under the title saying what the page
   is — this becomes the title-headed chunk and is what recalls when someone
   asks about the page's subject as a whole.
6. **Simplify prose, faithfully.** Tighten wording, cut filler, keep every
   fact. Never invent, editorialize, or flatten the user's meaning — the brain
   contract is RAW faithful facts; interpretation belongs to consumers.
7. **Titles and hierarchy for scoping.** Page titles become path segments —
   make them short nouns a `scope=` prefix would target. Group sibling pages
   under a parent per domain. Whole subtrees must be shared with the
   integration or the path truncates at the unshared ancestor (best-effort
   walk).
8. **Databases**: rows are themselves pages; the brain ingests DB child pages
   individually (page-only). Don't restructure database schemas — out of scope.

## Tools

**Notion writes** — the claude.ai Notion MCP connector. Load schemas first
(deferred): `ToolSearch "select:mcp__claude_ai_Notion__notion-fetch,..."`. The
useful set: `notion-search`, `notion-fetch`, `notion-update-page`,
`notion-move-pages`, `notion-create-pages`. Two caveats:
- The connector is authenticated as the **user**, not the brain's integration
  — it can see and edit pages the brain can't. Check edit targets against
  `GET /notion/pages` (what the integration sees, with `ingested` flags).
- It may be absent in headless runs; without it, do analysis + plan only and
  hand the user the edit list.

**Brain reads** — analysis substrate (local: `http://127.0.0.1:8100`; stack
startup + psql access: see the `test-brain` skill):

| Call | Use here |
|---|---|
| `GET /notion/pages` | full inventory: id, title, parent_id, kind, ingested |
| `GET /map?scope=` | ingested tree: paths, titles, versions |
| `GET /doc?id=` | a page's stored markdown verbatim — audit its structure |
| `GET /recall?q=&k=` | dedupe probe + before/after verification |
| `POST /ingest {url}` | re-derive chunks after each Notion edit |

## Dedupe sweep (the brain finds its own duplicates)

1. Enumerate chunks in scope:
   `psql ... -c "SELECT s.title, c.heading, left(c.text,300) FROM chunks c JOIN sources s ON s.id=c.source_id ORDER BY s.path, c.position"`
2. For each chunk with a body, probe `GET /recall?q=<first ~200 chars of
   body>&k=5`. The owning source should win; flag any hit from a **different**
   source scoring near it (scores are compressed — judge the gap, e.g. another
   source within ~10% of the self-hit, not absolute numbers).
3. Confirm each flag by reading both sections (`/doc` on each id) — same fact,
   or just same topic? Same topic ≠ duplicate; only true restatements get
   deduped. Genuine overlap of treatment → propose merging the two sections
   into the canonical page instead.
4. Output: a table of `fact → canonical page → pages to trim`.

## Flow

1. **Survey** — `/notion/pages` + `/map`: build the tree, mark what's
   ingested, agree the scope with the user (a subtree or page list). Never
   roam outside it.
2. **Audit** — `/doc` each page in scope; score against the checklist; run the
   dedupe sweep.
3. **Plan** — per page: exact before/after heading outline, sections to
   rewrite (with new text), dupes to remove + pointer lines, title renames,
   moves. Present the whole plan; **get explicit approval** (per page or
   batch).
4. **Apply** — execute via the Notion MCP tools, one page at a time.
5. **Re-ingest** — `POST /ingest` each touched page's URL; confirm the
   returned chunk count matches the planned outline.
6. **Verify** — recall battery: for each major section, one natural-language
   query that should hit it; confirm the right section + page wins, dupes no
   longer surface from trimmed pages, and an off-topic control stays low.
   Report before/after side by side.

## Safety rules (hard — no exceptions)

- **No write without an approved plan.** Show exact before/after for every
  page; silence is not approval.
- **Never replace a page with a copy.** Create-new + archive-old changes the
  page id and orphans the brain source (`sources.id` = Notion page id). Edit
  in place; move with `notion-move-pages` (moves preserve ids). If MCP can't
  do a move, ask the user to drag it in the Notion UI instead.
- **Archive, never permanently delete.** Archived pages/blocks are
  recoverable from Notion trash; deletions aren't.
- **Content is sacred, structure is yours.** Restructure, retitle, relocate,
  tighten — but every fact present before must be present after (on its
  canonical page). When trimming a dupe, diff the two passages first and fold
  any detail unique to the dupe into the canonical copy before removing it.
- **Stay in scope.** Only touch pages the user put in scope, even when the
  dedupe sweep implicates an outside page — report it, don't edit it.
- **Re-ingest immediately after editing** each page, so the brain is never
  stale against Notion. If ingest fails, stop and report before editing more.
