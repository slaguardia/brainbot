# Plan: Twitter content pipeline — a brain-native ghostwriting app ("Claude Code for tweets")

## Status: proposed (not started)

> Working app name: **scribe** (TBD). A platform app (L4) on the brain. This is a
> design spec, not a task checklist — the executable `.tasks/` breakdown is a
> follow-up (see [Next step](#next-step)).

## Context / problem

The owner already runs a sophisticated tweet-writing workflow **by hand** in
Notion under `Twitter/`:

- **Content inbox** — ~25 dated entries, each in a repeating shape:
  `Raw thought → Tweet drafts (multiple angles) → Framework fit → 4A audit → Notes`.
- **Content framework** — the lanes (Builder / Operator / Discipline), the
  70/20/10 mix, and the three post formats (discovery / mistake / insight).
- **Writing style** — voice characteristics and hard dislikes (no soft openers
  like "this hits", no empty insight, no absolutist framing).
- **Voice lens — Ambitious indie hacker** — the single filter every post passes
  through ("how does this advance my founder journey?").
- **Tweet generator**, **Tweet generator (shorthand)**, a **reply prompt**,
  **Searching for Tweets** — the prompt assets.

In other words: the owner has already authored, in prose, the entire "harness"
for turning a raw morning thought into audited, voice-consistent tweet angles.
The work today is manual repetition of that harness, one inbox entry at a time,
in a chat window.

This app automates that harness as a first-class platform app: read the brain
for *who you are and what you've written*, run the harness over an inbox item,
and produce angles already filtered through the framework, the lens, and the
style rules — then learn, app-locally, from which drafts you actually keep.

## Product thesis: "Claude Code for tweets"

The original framing was "build your own agent pipeline." The owner sharpened it
(2026-06-19):

> "Less of a *tool*, more of a *solution*. Design something complex enough to
> attach to the brain and just work. Keep configuration as minimal as possible.
> As complex as your Notion is detailed."

That is the load-bearing decision and it inverts the usual "no-code pipeline
builder" instinct. **The harness is not configured in the app — it is authored
in Notion and read live from the brain.** The `Tweet generator`, `Writing
style`, `Content framework`, and `Voice lens` pages *are* the pipeline's
configuration. Make those pages richer and the app gets smarter with zero
app-side settings. The app ships one opinionated, deep pipeline; the only choice
the user makes per run is **intent** (single tweet / thread / reply).

So the Claude-Code analogy is precise but re-pointed:

| Claude Code | scribe |
|---|---|
| `CLAUDE.md` / project context | the brain (`Writing style`, `Voice lens`, `Content framework`, past tweets) |
| the prompt you type | an inbox raw-thought entry (or a free idea) |
| sub-agents / tool calls in a turn | the pipeline stages (assemble → angles → audit → critique → score) |
| context retrieval injected into the prompt | `recall()` across the whole brain for supporting specifics |
| the harness that orchestrates it all | scribe's pipeline engine (fixed, brain-fed) |
| learning your preferences | app-local voice adaptation from kept/edited/rejected drafts |

It "just works" because the intelligence lives in two places that already exist:
the owner's curated Notion (read via the brain) and the LLM that reasons over it.
scribe is the thin, durable orchestrator between them.

## Where it fits the platform (the app contract)

scribe is a standard L4 app per [`app-platform.md`](../docs/app-platform.md):

- **Backend** that owns its own working-set store and reads the brain read-only
  over HTTP (`recall`/`doc`/`map`), via the app's own `/api/brain/*` proxy.
- **PWA** built from the [`web-toolkit`](../docs/web-toolkit.md) (vanilla TS +
  Vite, the shared shell/tokens/components, the brain client, `currentUser()`).
- **One Caddy vhost** `scribe.{domain}` → `forward_auth` → the app. Inherits
  HTTPS + Google SSO; no login code in the app.
- **Launcher entry** in the brainbot dashboard's app registry.

The two-kinds-of-data rule maps cleanly and is the reason the owner's "app-local
adaptation only" answer is the *correct* architecture, not a compromise:

| Data | Kind | Lives in |
|---|---|---|
| Voice, framework, lens, style, prompts, raw thoughts, past tweets | knowledge **about you** | the **brain** (you curate it by editing Notion) |
| Pipeline runs, generated angles, your ratings/edits, queue + post status, learned exemplars | scribe's **working set** | scribe's **own store** |

Because voice learning is app-local, scribe **never writes the brain** and there
is no write-back-to-Notion machinery to build or approve. Every platform
invariant holds untouched. The brain stays human-curated; the app accumulates
its own disposable, rebuildable working set — exactly the boundary the platform
draws.

## Design principles (non-negotiable)

- **The harness lives in Notion, not the app.** Pipeline behavior derives from
  brain pages read live. No second authoring surface, no in-app prompt editor in
  v1. Edit the page → re-ingest → the pipeline changes. (Mirrors the brain's own
  "editing the brain is editing the page" ethos.)
- **The brain retrieves; scribe reasons.** All LLM reasoning (drafting,
  auditing, scoring) happens in scribe's backend over passages `recall()`
  returns. The brain stays LLM-free on the read path. (`architecture.md`.)
- **Two kinds of data, never mixed.** scribe's tables never enter the brain's
  `sources`/`chunks`. The brain is read-only for scribe.
- **App-local voice learning.** Adaptation is derived from scribe's own
  behavioral working set and injected as few-shot context. It is never promoted
  to the brain automatically (the brain has no auto-accumulated memory).
- **Minimal configuration.** Per-run choice is intent only. Depth comes from the
  Notion pages, not from settings.
- **Faithful provenance.** When a draft is enriched with a specific fact, scribe
  tracks which brain source/chunk it came from, so a draft is traceable back to
  the owner's own words — never a hallucinated specific.

## Architecture

```
                         scribe.{domain}  (Caddy vhost, Google SSO at the edge)
                                  │
                    ┌─────────────┴──────────────┐
                    │  scribe backend (Node/TS)   │
                    │                             │
   PWA (toolkit) ──▶│  /api/*        app logic    │
                    │  /api/brain/*  read proxy ──┼──▶ brain  (recall/doc/map)  [read-only]
                    │  /api/me       edge identity│
                    │  pipeline engine ───────────┼──▶ Claude API  (drafting/audit/score)
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                        scribe DB (own SQLite database — a file, like scout)
                        runs · generations · drafts · queue · feedback · exemplars
```

### Backend — Node/TS (recommended)

The job is LLM orchestration + a durable store + streamed progress + a small
queue. That is thin-CRUD-plus-orchestration, which Node fits best: first-class
Anthropic SDK, trivial SSE for live pipeline progress (scout already
establishes an SSE progress view in the toolkit), and it shares TypeScript with
the toolkit. (Polyglot is allowed; this is a recommendation, not a mandate.)

### Store — SQLite, like scout

scribe's working set lives in its own **SQLite database** (a file on the app's
volume), exactly as scout does. It must persist — learned voice exemplars and
edit history *are* the "learning over time" — but durability is not the engine's
job: SQLite persists to disk as durably as Postgres. The factors that would push
toward Postgres don't apply here: scribe is single-user (no concurrent writers),
its working set is small (one owner's drafts), and v1 selects exemplars by
recency/strength score, not semantic similarity (no pgvector). Matching scout
keeps the platform consistent — no separate database to provision. The two-kinds
boundary holds untouched: SQLite is scribe's own store, never the brain's schema,
so scribe still cannot touch the brain's data.

> *Future:* if exemplar selection ever wants *semantic* retrieval ("find drafts
> like this one"), that needs embeddings — at which point a dedicated Postgres
> database with pgvector (same server, separate database) becomes the natural
> home. Out of v1 scope; the schema is small enough to port if it earns it.

### LLM — Claude API

scribe is the reasoning layer. Suggested model assignment (revisit with cost):

- **Drafting + revision** — `claude-sonnet-4-6` (the workhorse; voice-sensitive
  generation at good cost).
- **Audit/critique pass** (lens + style + 4A) — `claude-opus-4-8` optionally,
  for the highest-judgment step; Sonnet is fine to start.
- **Cheap classification** (lane tagging, intent guess) — `claude-haiku-4-5`.

`ANTHROPIC_API_KEY` is a new app secret (alongside the brain bearer token);
embeddings stay Voyage on the brain side, unaffected.

### How scribe reads Notion: through the brain, not directly

The platform's rule is *the brain is the one Notion reader; apps read the brain.*
So scribe does **not** call the Notion API. Instead, the relevant `Twitter/*`
pages are ingested as brain sources (the [prerequisite
ingest](#prerequisite-ingest)) and scribe reads them via `recall`/`doc`/`map`.
This also unlocks the best feature for free (below): cross-brain enrichment.

## The pipeline engine (the heart)

One fixed, opinionated pipeline. The user picks an **intent**; everything else
is derived from the brain. Stages, each grounded in specific brain content:

**Stage 0 — Intake.** Source is either an inbox entry (a `Content inbox` child
page) or a free-typed idea. For an inbox entry, `doc(id)` fetches the raw
thought verbatim.

**Stage 1 — Context assembly.** Two recalls:
1. *Voice substrate* — `recall()` against the `Writing style`, `Voice lens`,
   `Content framework`, and the relevant prompt page (`Tweet generator` for a
   single tweet, the reply prompt for a reply). These passages become the system
   instruction for the run. This is the "harness authored in Notion" — the
   prompts are read, not hard-coded.
2. *Cross-brain enrichment* — `recall(<the raw thought>)` across the **whole**
   brain to pull concrete supporting material from anywhere in the owner's
   notes. This is the "useful info detected by the brain" the owner asked for: a
   thought about Postgres tuning recalls the actual `work_mem incident` page, so
   the draft can cite a real specific instead of a vague claim. Provenance is
   tracked per [Faithful provenance](#design-principles-non-negotiable).

**Stage 2 — Angle generation.** Produce N angles (default 4, matching the inbox
format) using the framework's formats (discovery / mistake / insight) and any
learned exemplars (see [voice adaptation](#app-local-voice-adaptation-the-learning-loop)).

**Stage 3 — Framework + lens audit.** Each angle is scored against:
- the **Voice lens** checklist (does it advance the founder journey? is it
  in-the-arena first person? standalone-clear? only-I-could-write-it?),
- the **70/20/10 lanes** (tag the angle's lane),
- the **4A audit** (Actionable / Analytical / Aspirational / Anthropological).

**Stage 4 — Style critique + revise.** Check each angle against the `Writing
style` dislikes (kill soft openers, empty "this hits", absolutist framing,
performative voice) and revise. The dislikes list is read from the brain, so
tightening that Notion page tightens the critique.

**Stage 5 — Score, rank, assemble.** Rank angles by a composite (lens fit +
style cleanliness + hook strength), and assemble the output in the **owner's own
inbox shape**: `Raw thought → Drafts (angles) → Framework fit → 4A audit →
Notes`. Saved to scribe's store as a **generation**.

Progress streams to the PWA over SSE (toolkit pattern), so a run reads like a
Claude Code turn: you watch the stages think.

**Why this honors "minimal config / as complex as your Notion."** The only knob
is intent. Everything that makes the output good is read from Notion at runtime.
The pipeline is fixed in code; its *intelligence* is a function of how detailed
the brain is. Enriching `Voice lens` or adding a new format to `Content
framework` immediately changes every future run — no deploy, no settings.

### Pipeline intents (v1)

| Intent | Brain prompt page read | Output |
|---|---|---|
| Single tweet | `Tweet generator` | N standalone angles |
| Thread | `Content framework` formats | an ordered multi-tweet draft + alt hooks |
| Reply | the conversational reply prompt | a style-locked reply to pasted context |

"Intent" is the *entire* per-run configuration surface.

## App-local voice adaptation (the learning loop)

This is "learn your voice over time," kept entirely in scribe's store (the
owner's chosen model):

- **Capture.** For each generation, record: the angles produced, which the user
  **kept / edited / rejected**, the **final edited text** (and its diff vs. the
  generated text), a thumbs signal, and whether it reached `posted`.
- **Distill.** Maintain a rolling, app-local set of **voice exemplars**:
  - *Positive* — drafts kept verbatim or lightly edited, and posted ones ("this
    is exactly my voice").
  - *Negative* — rejected or heavily rewritten drafts ("avoid this").
  - *Edit patterns* — recurring transforms (e.g. "user consistently deletes the
    opening line", "user shortens"), mined from the diffs.
- **Apply.** Inject the strongest positive exemplars (and a short "avoid" list)
  as few-shot context into Stages 2 and 4 of future runs. The voice sharpens
  with use, grounded in real accept/reject behavior rather than self-report.

Nothing here touches the brain. It is scribe's working set: disposable in
principle (you could wipe it and the app still works from the Notion substrate),
durable in practice (so the learning compounds). That is precisely the
two-kinds-of-data boundary.

> *Future, explicitly out of v1 scope:* scribe could **suggest** "your voice has
> drifted from your `Writing style` page — here's a proposed edit" for the owner
> to apply in Notion by hand. That keeps the human-curated invariant (the app
> never writes the brain) while letting durable learning graduate into the
> substrate. Noted, not built — the owner chose app-local-only for now.

## Output: the schedule queue

The owner chose an **in-app schedule queue** (no X API write in v1):

- **Statuses:** `idea → drafting → ready → scheduled → posted`. (`drafting` is a
  generation in flight; `ready` is a chosen/edited draft; `scheduled` carries an
  intended date; `posted` is marked by hand after the user posts.)
- **Cadence view** seeded from the `Content framework` cadence (2–3/week
  minimum, ~1/day ideal) — a simple calendar showing what's queued and gaps.
- **Post-out is manual:** copy-to-clipboard (single tweet or whole thread) +
  "mark posted." A posted draft becomes a high-signal positive voice exemplar.
- **Direct X publishing is a non-goal for v1** (OAuth, write tokens, rate
  limits, paid API tier). The queue is designed so adding an X "publish" action
  later is a localized change, not a rearchitecture.

## App working-set data model (sketch)

In scribe's own database (names illustrative):

- `runs` — one pipeline execution: intent, source (inbox `doc` id or free text),
  status, timing, model + token cost, the assembled brain context snapshot.
- `generations` — the assembled inbox-shaped artifact per run.
- `drafts` — individual angles: text, lane tag, 4A tags, lens-fit + style
  scores, rank, and the user's disposition (kept/edited/rejected) + final text.
- `enrichments` — per draft, the brain source id/chunk + score used as a
  supporting specific (provenance).
- `queue_items` — a chosen draft promoted to the queue: status, scheduled_at,
  posted_at.
- `voice_exemplars` — distilled positive/negative examples + mined edit patterns
  feeding future prompts.
- `settings` — minimal (default angle count, model overrides). Deliberately thin.

No table here is a fact about the owner; all of it is rebuildable derived output.

## Brain reads + prerequisite ingest

### Reads scribe makes

- `map(scope="…/Twitter/Content inbox")` — enumerate inbox entries (the work
  queue). *(Depends on `/map` scope semantics; if path-scoped map is awkward,
  fall back to `map()` + path filter.)*
- `doc(id)` — fetch a specific inbox raw thought verbatim.
- `recall(q)` — voice substrate (Stage 1.1) and cross-brain enrichment
  (Stage 1.2).
- `changes(since)` (via the toolkit's `onChange`) — invalidate scribe's cached
  brain context when the owner edits a `Twitter/*` page, so harness changes show
  up without a TTL.

### Prerequisite ingest

These Notion pages must be ingested as brain sources before scribe is useful
(human-curated, not automatic — flagged per the build-platform-app contract):

- `Twitter/Writing style`
- `Twitter/Voice lens — Ambitious indie hacker`
- `Twitter/Content framework`
- `Twitter/Tweet generator` (+ shorthand), the reply prompt, `Searching for
  Tweets`
- `Twitter/Content inbox` and its child entries (the input queue **and** a rich
  past-tweet corpus for voice grounding)

A `Content inbox` whose entries are already ingested doubles as both the work
queue and a large set of past, human-written tweets — the best possible voice
grounding, for free.

## Frontend (toolkit PWA) — views

All from the web-toolkit shell; vanilla TS; toolkit components only.

1. **Inbox** — brain-sourced list of `Content inbox` entries (via `map`/`doc`),
   each with a "run pipeline" action and its generation status.
2. **Run** — live SSE stage-by-stage progress (the "watch it think" view),
   reusing scout's progress component.
3. **Review** — the generation: angles side-by-side with lane/4A/score chips;
   keep / edit-inline / reject; "send to queue." Editing here is the primary
   voice-learning signal.
4. **Queue / calendar** — the cadence board; copy-out; mark posted.
5. **Voice** — read-only window into what scribe has learned (top positive/
   negative exemplars, mined edit patterns) + links to the source Notion pages,
   so the learning is legible and trustable.

## Milestones (each independently shippable)

1. **M0 — Prerequisite ingest + read spike.** Ingest the `Twitter/*` pages;
   confirm `recall`/`doc`/`map` return the voice substrate and inbox usefully.
   No app yet — validates the substrate.
2. **M1 — Backend skeleton on the contract.** `/api/me`, `/api/brain/*` proxy,
   the SQLite store, and a one-shot pipeline endpoint that runs Stages
   0–5 for a single tweet and persists a generation. No learning, no queue.
3. **M2 — PWA: Inbox → Run (SSE) → Review.** The core loop end to end behind the
   edge; keep/edit/reject captured.
4. **M3 — Voice adaptation.** Distill exemplars from M2's captured dispositions;
   inject into prompts; the Voice view.
5. **M4 — Queue + cadence + thread/reply intents.** The schedule board, manual
   post-out, and the two additional intents.
6. **M5 — Launcher + polish.** Registry entry, health endpoint, icons, offline
   shell.

Each milestone is a normal app increment; M1 is gated on M0.

## Invariants honored (the platform checklist)

1. Brain holds knowledge about you; scribe holds its own working set. ✅ (no
   write-back; app-local learning.)
2. Backend renders no HTML; `/api/*` JSON + toolkit PWA. ✅
3. One design system / shell / SW, from the toolkit; no third-party component
   library. ✅
4. Auth at the edge; no login code in scribe. ✅
5. Polyglot backend allowed; bespoke frontend not. ✅ (Node by choice, toolkit
   PWA by rule.)

## Non-goals (v1)

- Direct posting/scheduling to X (no X API). Queue is manual post-out.
- An in-app prompt/pipeline editor or visual DAG builder (the harness is
  authored in Notion).
- Writing anything back to the brain / Notion (no capture; learning is
  app-local).
- Multi-account / multi-user (single-user platform, like everything here).
- Analytics on posted-tweet performance (engagement) — a strong future input to
  voice learning, but out of scope until there's an ingestion path.

## Open questions

- **Path-scoped `map`** for enumerating just the `Content inbox` subtree — is
  `scope=` precise enough, or does scribe filter `map()` by path client-side?
- **Free-idea intake** vs. inbox-only: v1 supports both, but does a free idea
  also get written somewhere durable, or stay a transient run? (Leaning:
  transient run; the inbox stays the human-curated source.)
- **Enrichment aggressiveness** — how strongly Stage 1.2 should inject
  cross-brain specifics before it starts to dilute the owner's raw thought. Make
  it a scored suggestion the user can accept per-draft, not an automatic
  rewrite.
- **Cost ceiling per run** — 4 angles × an Opus audit can add up; default to
  Sonnet throughout and make the Opus audit opt-in.
- **Exemplar selection** — recency vs. strength weighting, and a cap so the
  few-shot context stays small.

## Next step

Per the `build-platform-app` skill, the follow-up to this spec is an executable
`.tasks/FEAT-…/` checklist (`feature.json` + `stories/US-*.json`, dependencies
wired) covering M0–M5, then scaffold. This doc is the architecture input to that
breakdown; the skill is the procedure.

## Related docs

- [`app-platform.md`](../docs/app-platform.md) — the app contract, two-kinds
  rule, edge, launcher (governing doc).
- [`web-toolkit.md`](../docs/web-toolkit.md) — the PWA package scribe builds on.
- [`consumer-api.md`](../docs/consumer-api.md) / [`consumer-integration.md`](../docs/consumer-integration.md)
  — the exact `recall`/`doc`/`map`/`changes` contract scribe's brain client wraps.
- [`architecture.md`](../docs/architecture.md) — the brain + edge; the
  "brain retrieves, app reasons" boundary scribe sits on.
</content>
</invoke>
