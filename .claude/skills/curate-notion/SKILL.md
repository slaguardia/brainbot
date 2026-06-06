---
name: curate-notion
description: Keep a Notion workspace healthy and brain-ready — restructure pages into self-describing sections, reword for clarity, file loose pages into the hierarchy, dedupe facts across pages, surface stale/empty/duplicate pages, and keep the brain's ingest in sync. Reorganization and rewording are applied directly; anything that removes content is surfaced for approval first. Use when asked to optimize, clean up, reorganize, curate, or dedupe Notion.
---

# Curating Notion for the brain

The brain ingests Notion pages and splits them into **one chunk per heading
section** (`brain/brain/store.py`, `_split_sections`). Recall quality is
therefore mostly determined by how pages are written: heading structure, one
topic per section, one home per fact. This skill is how to curate the Notion
workspace itself — via Notion MCP write tools — so the source material
retrieves well and the workspace stays tidy. It works as a one-off cleanup or
a recurring curation pass. Design context: `brain/ARCHITECTURE.md`.

## Operating contract (what needs approval)

**Do without asking** — reversible, content-preserving edits. Apply them
directly and report what changed afterward:

- restructuring headings; splitting or merging sections within a page
- rewording and tightening prose (faithfully — every fact survives)
- retitling pages and headings; renaming for uniqueness
- moving pages within the hierarchy (moves preserve page ids)
- adding purpose preambles and plain-text pointer lines
- fixing pointer lines that name a page's old title after a rename
- re-ingesting edited pages into the brain

**Surface first, act only on approval** — anything that removes content.
Collect candidates into a *deletion docket*: what, where, why, and where the
content survives. Present the docket, act only on the approved entries:

- trimming a duplicated passage from a non-canonical page
- removing a section or block outright
- archiving a page (stale, empty, superseded, merged-away)

**Never** — hard rules, no exceptions:

- permanently delete anything — archive only (recoverable from Notion trash)
- replace a page with a copy: create-new + archive-old changes the page id
  and orphans the brain source (`sources.id` = Notion page id). Edit in
  place; move with the MCP move tool. If moving isn't available, ask the
  user to drag the page in the Notion UI.
- invent, editorialize, or flatten meaning — the brain contract is RAW
  faithful facts; interpretation belongs to consumers
- touch pages outside the agreed scope, even when a sweep implicates one —
  report it instead

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
  results. (Scores are compressed — judge relative gaps, never absolutes.)

## Page-level checklist

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
   treatment), keep it there, and on the other pages trim the duplicate
   (docket) and leave a one-line plain-text pointer naming the canonical page
   title ("Salary details live in [[Compensation]]"). Title mentions survive
   ingest as searchable text; inline URLs don't.
5. **Purpose preamble.** 1–3 plain lines under the title saying what the page
   is — this becomes the title-headed chunk and is what recalls when someone
   asks about the page's subject as a whole.
6. **Simplify prose, faithfully.** Tighten wording, cut filler, keep every
   fact.
7. **Title hygiene.** Page titles become path segments — short nouns a
   `scope=` prefix would target. Two pages with the same title confuse paths
   and `[[pointers]]`: rename for uniqueness.
8. **Databases**: rows are themselves pages; the brain ingests DB child pages
   individually (page-only). Curate row-page *content*; don't restructure
   database schemas — out of scope.

## Workspace-level curation

Beyond single pages, sweep the whole scope for:

- **Loose pages → file them.** Root-level or misplaced pages that belong
  under a domain parent: move them (no-ask). Domains as top-level parents
  make `scope=` filters work; whole subtrees must be shared with the
  integration or the path truncates at the unshared ancestor.
- **Duplicate pages → merge.** Two pages about the same thing: fold the
  lesser page's unique content into the canonical one (no-ask additions),
  then docket the husk for archive.
- **Contradictions → ask.** The same fact stated incompatibly on two pages
  (numbers, dates, decisions that changed). The skill can't know which is
  current — present both and ask, then fix the loser like any dupe.
- **Stale pages → docket.** Long-unedited pages superseded by newer ones
  (`last_edited_time` from `/notion/pages`): candidates for archive, never
  auto-archived.
- **Empty / stub / untitled pages → docket** (or retitle, if the fix is a
  title rather than removal).
- **Sync drift → re-ingest.** Ingested pages edited after their last ingest
  (compare `/notion/pages` `last_edited_time` against what the brain serves):
  re-ingest them (no-ask). Pages shared with the integration but never
  ingested: list them for the user rather than auto-ingesting.

## Tools

**Notion writes** — any connected Notion MCP server with write tools
(e.g. the claude.ai Notion connector). Discover the tool names with
ToolSearch; the useful set is search, fetch, update-page, move-pages,
create-pages. Two caveats:
- The MCP server may authenticate as the **user**, not the brain's
  integration — it can see and edit pages the brain can't. Check edit targets
  against `GET /notion/pages` (what the integration sees, `ingested` flags).
- It may be absent in headless runs; without it, do analysis + docket only
  and hand the user the edit list.

**Brain reads** — the analysis substrate, over HTTP (local default
`http://127.0.0.1:8100`, or the deployed brain URL — see the `test-brain`
skill for stack startup):

| Call | Use here |
|---|---|
| `GET /notion/pages` | full inventory: id, title, parent_id, kind, last_edited_time, ingested |
| `GET /map?scope=` | ingested tree: ids, paths, titles, versions |
| `GET /doc?id=` | a page's stored markdown verbatim — audit its structure |
| `GET /recall?q=&k=` | dedupe probe + before/after verification |
| `POST /ingest {url}` | re-derive chunks after each Notion edit |

## Dedupe sweep (the brain finds its own duplicates)

1. Enumerate sections in scope: `GET /map?scope=` for source ids, then
   `GET /doc?id=` per source — split on heading lines to recover each
   section's heading and body.
2. For each section with a body, probe `GET /recall?q=<first ~200 chars of
   body>&k=5`. The owning source should win; flag any hit from a **different**
   source scoring near it (judge the gap — e.g. another source within ~10% of
   the self-hit — not absolute numbers).
3. Confirm each flag by reading both sections — same fact, or just same
   topic? Same topic ≠ duplicate; only true restatements get deduped. Genuine
   overlap of treatment → propose merging into the canonical page instead.
4. Fold any detail unique to the duplicate into the canonical copy (no-ask),
   then docket the trim: `fact → canonical page → pages to trim`.

## Flow

1. **Survey** — `/notion/pages` + `/map`: build the tree, mark what's
   ingested, agree the scope with the user (a subtree, page list, or the
   whole workspace). Never roam outside it.
2. **Audit** — `/doc` each page in scope; score against the page checklist;
   run the dedupe sweep and workspace sweeps.
3. **Tidy** — apply every no-ask edit (restructure, reword, retitle, move,
   file, preambles, pointers), one page at a time, re-ingesting each page as
   it's edited. If an ingest fails, stop and report before editing more.
4. **Docket** — present every removal candidate with rationale and where the
   content survives; apply only what's approved; re-ingest affected pages.
5. **Verify** — recall battery: for each major section touched, one
   natural-language query that should hit it; confirm the right section +
   page wins, trimmed dupes no longer surface, and an off-topic control stays
   low. Report before/after, plus everything changed in Tidy.
