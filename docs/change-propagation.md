# Change-aware brain reads — a propagation SDK (proposal)

> Companion to [`app-platform.md`](./app-platform.md) and
> [`consumer-integration.md`](./consumer-integration.md). Those docs answer "how
> do apps read the brain." This one answers the question that shows up once an app
> *caches* what it read: *how does a consumer know when its cached view of the
> brain is actually out of date — without polling on a dumb timer?* Status:
> **proposal, not yet built.** Written 2026-06-09. First motivating consumer:
> scout's company-fit brief cache.

## The problem this solves

Apps don't read the brain on every request — that's expensive (recall fan-out +,
for scout, an LLM distillation on top). So they cache a derived view and re-read
on a **TTL**: "if the cache is older than N hours, refetch."

A TTL measures the **wrong thing**. It measures *time elapsed*, then the UI
displays it as *out of date*. Those are not the same, and the gap produces two
concrete bugs, both live in scout today:

1. **The staleness badge lies.** Scout's criteria panel shows "stale" whenever
   `age ≥ TTL`, even when the brain hasn't changed a byte. The user sees "stale"
   and distrusts a brief that is, in fact, current.
2. **Refresh does needless work — and can *introduce* drift.** On TTL expiry
   scout re-runs the full distillation (recall + two LLM calls) even when nothing
   moved. Worse, the LLM synthesis isn't byte-stable, so a *no-op* refresh can
   change the visible brief prose — a refresh that should have been a silent
   confirmation instead wobbles the output.

The root cause is that **"when to re-check" and "did it change" are conflated
into one timer.** Separate them and both bugs disappear.

## The reframe: a timer decides *when to look*, a content stamp decides *what changed*

The brain already publishes the signal we need. Every page in `/map` and `/doc`
carries a **`version`** — a content stamp that "moves iff `{title, text}`
change; never on a mere re-sync or a path change" (see
[`consumer-api.md`](./consumer-api.md)). That is exactly a per-page change hint,
already built, already trustworthy. No app is using it for *invalidation* yet —
only for `/doc` body caching.

So change-aware reads decompose into a **cost cascade**, where each tier only
fires the next when something genuinely changed:

| Tier | Cost | Answers | Fires next tier when |
|---|---|---|---|
| **0 — change signal** | 1 cheap HTTP call, no LLM | "did *anything relevant* in the brain change?" | signal ≠ stored |
| **1 — relevance gate** | the app's read fan-out, no LLM | "did the content *this view draws from* change?" | basis hash ≠ stored |
| **2 — recompute** | the app's expensive derivation (for scout: LLM synthesis) | produce the new derived view, bump its version | reached only on real change |

The timer's job shrinks from *trigger* to *fallback ceiling*: "re-run Tier 0 at
most every N hours, in case the signal is ever unavailable." Steady state is one
cheap call per check and **zero expensive work until the brain actually moves.**

## Tier 0 — the change signal (what the brain exposes)

Two options, cheapest first:

### Option A — derive it from `/map` today (zero brain work)

`/map` already returns `{sources:[{id, title, path, parent_id, version}]}`. A
consumer hashes the `(id, version)` set into a single **map fingerprint** and
stores it beside its cache. Next check: re-fetch `/map`, re-hash, compare.

- **Pro:** ships now, needs no brain change.
- **Con:** one `/map` call per check (cheap, but not free), and the fingerprint
  is **global** — any brain edit anywhere advances it, even an irrelevant note.
  That over-triggering is *absorbed by Tier 1*, so it's correct, just slightly
  wasteful at Tier 0.

### Option B — a dedicated change cursor (small brain work, the real answer)

Add one endpoint to the brain's read surface:

```
GET /changes?since=<cursor>  →  { cursor: "<opaque>", changed: true|false }
```

or, even simpler, a monotonic global stamp:

```
GET /version  →  { version: "<stamp over max(updated_at) across sources>" }
```

The app stores the last `cursor`/`version` and polls it. Backed by
`max(updated_at)` (or a changelog table) over `sources`, it's a single indexed
query — far cheaper than `/map`, and it's the natural substrate for the SDK's
push upgrade later (a cursor is already the right shape for a replayable feed).

**Recommendation:** start with **Option A** (the toolkit's brain client can do it
unilaterally, unblocking scout immediately), and add **Option B** when a second
caching consumer exists or `/map` payloads grow enough that fingerprinting them
per check stings. The SDK interface (below) is identical either way — A vs B is
an implementation detail behind `onChange`.

## Tier 1 — the relevance gate (app-side, already half-built in scout)

Tier 0 says "the brain moved." It does **not** say "the part *I* derive from
moved." Tier 1 narrows it: the app re-runs its read (for scout, the recall
fan-out) and hashes the result into a **basis** — exactly scout's existing
`content_hash`, "the synthesis prompt + recalled chunk content"
(`brain_profile_cache.content_hash`). If the basis matches the stored one, a page
changed but **not one this view draws from** → skip the expensive recompute,
just re-stamp `verified_at`. If it differs → Tier 2.

This tier is what makes global over-triggering at Tier 0 harmless, and it's why
the map fingerprint can stay dumb and global.

## The SDK: a transport-agnostic `onChange` (the load-bearing idea)

The point of routing this through an **SDK** — the brain client that already
lives in the L3 toolkit (`app-platform.md`, "what's in the web toolkit") — rather
than per-app code is that the *programming model* and the *transport* get
decoupled. The SDK exposes one change primitive:

```ts
// L3 toolkit brain client — proposed addition
brain.onChange(() => revalidate())   // fires when the brain's content moves
```

Today `onChange` is implemented by **polling** Tier 0 (Option A or B) on an
interval. If true push is ever justified, the brain grows an SSE/webhook feed and
`onChange` swaps polling for a subscription **inside the SDK** — and **no
consumer app changes**, because they only ever called `onChange`. This is the
move that lets us get the event-driven *feel* now while paying only for polling,
and defer the real-infrastructure decision indefinitely.

| Concern | Lives in | Why |
|---|---|---|
| "did it change?" signal | the **brain** (`/map` version today; `/changes` cursor later) | only the write side knows |
| poll-vs-push, fingerprint, debounce | the **SDK** (toolkit brain client) | one implementation, every app inherits it |
| relevance gate (basis hash) + recompute | the **app** | only the app knows what its view derives from |

## Why not a real event bus (the honest pushback)

The instinct is "push, so updates are always instant." For this estate that's
over-engineering, and the doc should say so plainly:

- **The data is human-paced.** The brain changes when *you* edit your notes —
  rare, not high-frequency. A derived view being seconds-vs-minutes behind has
  near-zero value for a single-user tool like scout.
- **A real bus is a standing cost.** Change-capture in the brain's write path,
  fan-out (SSE/webhooks), persistent-connection management, reconnect + replay
  semantics, per-app subscription state, and the ops to keep it all alive — for a
  benefit no one will feel.
- **Polling a cursor gets ~90% for ~10%.** A 30–60 s poll of a one-query endpoint
  is *effectively* instant here, with no long-lived connections to babysit.

So: **build the cascade and the cursor; do not build the bus.** Let the SDK's
`onChange` interface make push a future implementation swap, not an architecture
commitment we make today. (This mirrors the doc's existing posture on toolkit
distribution: "git-tag dependency to start; private registry once churn hurts" —
start cheap, upgrade when it bites.)

## Relationship to the platform

- **L1 (brain).** The only possible brain change is **additive and read-only**: a
  `/changes`/`/version` endpoint. It does not violate invariant 1 — consumers
  still only read; nothing writes the brain.
- **L3 (toolkit).** `onChange` is a new method on the existing **brain client**
  row of the toolkit table. Every app inherits change-awareness for free — the
  same "get it right once" logic the toolkit exists for.
- **L4 (apps).** Each app keeps its own Tier 1 + Tier 2 (relevance gate +
  recompute) because only the app knows what its cached view is derived from.
  Scout already has the pieces (`brain_profile_cache`, `content_hash` basis); it
  gains a `map_fingerprint`/`cursor` column + a `verified_at` stamp and drops the
  age-based "stale" badge for an honest state.

## First consumer — scout (the proving ground)

Scout is the natural first migrant because the bug is live there. Concrete
mapping onto today's code:

1. Add `map_fingerprint` (or `cursor`) and `verified_at` columns to
   `brain_profile_cache`.
2. On `Resolve`: Tier 0 (compare fingerprint) → if unchanged, stamp `verified_at`
   and return the cached brief **untouched** (kills the no-op prose wobble). If
   changed → Tier 1 recall + basis compare (scout's existing `content_hash`) → if
   unchanged, skip synthesis; else Tier 2 re-distill + bump `Version` + re-score.
3. Replace the `stale = age ≥ TTL` field the criteria panel shows with a real
   tri-state: **Current** (basis verified unchanged), **Checking/Unverified**
   (TTL elapsed, not yet re-checked), **Changed** (basis differs → re-distilling).
   Keep the TTL only as a long fallback ceiling (e.g. 24 h).

Net for scout: steady state is one cheap brain call per check, **zero LLM spend
and zero brief wobble until the brain changes in a way that touches the
criteria**, and a badge that reflects content, not a clock.

## Open questions (decide when they bite)

- **Tier 0 transport.** `/map` fingerprint (zero brain work, ship now) vs a
  `/changes` cursor (small brain work, cheaper + push-ready). Start with the
  fingerprint; add the cursor at the second caching consumer.
- **Poll interval / who drives it.** A live PWA can poll on focus + an interval;
  a long-running backend (scout's `serve`) revalidates lazily on the next read.
  Pick per-consumer; the SDK exposes the primitive, not the schedule.
- **Push, ever.** Only if a genuinely change-latency-sensitive consumer appears
  (e.g. a multi-user app). Until then the `onChange` interface holds the seam;
  don't build the bus.

## How this relates to the other docs

- [`app-platform.md`](./app-platform.md) — the four-layer model; this proposal
  adds `onChange` to L3's brain client and (optionally) one read endpoint to L1.
- [`consumer-api.md`](./consumer-api.md) / [`consumer-integration.md`](./consumer-integration.md)
  — the `version` stamp this whole design leans on, and the cache rules it
  extends from *body caching* to *invalidation*.
- scout's `docs/north-star.md` + `CLAUDE.md` — the `brain_profile_cache` / TTL /
  distiller machinery this proposal upgrades in scout specifically.
