# What's actually valuable here

> **Dated framing (graph era).** Written when the brain was "a debugged Graphiti
> deploy." The brain is now a **Postgres + pgvector document substrate** built and
> owned in-repo (no graphiti, no FalkorDB) — so the value story shifts from
> "wrapping Graphiti" to "owning a hand-built RAG pipeline." The accounting below
> is kept for context; see
> [`../plans/document-substrate-exploration.md`](../plans/document-substrate-exploration.md)
> (the "RAG: the hood is open" angle) for the current framing.

An honest accounting of what this project is worth and to whom — written so we don't accidentally start believing our own framing.

## The brutal version

What exists right now is: an opinionated wrapper around [Graphiti](https://github.com/getzep/graphiti) that fixes about a dozen real bugs in their published Docker image, plus a generic text-ingest CLI, plus a smoke suite, plus operational documentation.

That's not nothing — it represents 1–2 weeks of debugging work that anyone else trying to deploy Graphiti would also hit. But it's also not a novel architecture, not a new algorithm, not even a new product category. The underlying tech (property graph + bi-temporal facts + LLM-driven entity extraction) is upstream's.

If we stop here, the project reads as **"a debugged Graphiti deploy"**. That's a legitimate but small contribution.

## Where the real value lives

Value compounds along three axes. Today we're only on the first one:

| Axis | Status | Who it's valuable to |
|---|---|---|
| **Operational debt removed** | ✅ exists | Anyone deploying Graphiti themselves hits the same gotchas. The "Known limits" section of the README + the custom image + the env-handling fixes save them days. |
| **Easy self-hosting (one-command setup)** | ❌ not built | A non-dev or junior dev should be able to `clone → run script → working brain on their VPS in 20 min`. Right now it requires understanding Docker, Compose, FalkorDB, env files, RediSearch syntax, etc. Until this exists, the audience is "people who would have figured Graphiti out themselves anyway." |
| **Demonstrated pattern with example consumer apps** | ❌ not built | The "one personal brain, many narrow agent apps" pattern only *means* something when there are 2–3 actual apps using it. Without examples, the project is asserting a pattern, not demonstrating one. |

The honest framing: today this is a personal tool for the author. With the self-host UX *and* 2–3 working example consumers, it becomes a thing other people might want to use, fork, or pay for.

A blunter way to phrase it: right now this is a portfolio piece **about** a self-hosted brain. With the missing two pieces above, it becomes a self-hosted brain **with case studies**. The latter is much harder for an outside observer (interviewer, prospective user, blog reader) to dismiss as "you wrapped some open source."

## Specific value plays worth building

These three are the highest-leverage moves once Phase 1 close-out is done. Each one unlocks more value than the previous work combined.

### 1. One-command self-host script

`curl -sSL install.brainbot.example.com | sh`. The script:

- Detects platform (laptop vs VPS)
- Prompts for the required API keys (Anthropic, Voyage)
- Generates the bearer token
- Writes a clean `.env`
- Pulls the compose, builds the custom image, runs the smoke
- Tells the user what URL their brain is at and what to put in `.mcp.json`

Hides every gotcha we hit. Audience: anyone who wants this pattern but doesn't want to spend two weeks debugging.

### 2. Hosted demo brain

A public brain that anyone can write to with a free key, scoped to a sandbox group, wiped nightly. Lowers the "trial barrier" from 30 minutes (install everything) to 30 seconds (`curl` the demo, see it work).

Doesn't replace self-hosting — the pitch is "if you like this, run your own." But seeing it work in 30 seconds is the difference between "I'll try this when I have time" and "I'm trying this now."

### 3. Reference consumer per category

One CLI tool, one web app, one mobile capture (the PWA). Each under ~300 lines. Each demonstrates a different shape of brain consumption:

- **CLI** — deterministic, scripted, the job-fit-scorer pattern
- **Web app** — interactive read-only browse over the brain
- **Mobile capture** — write-only quick-input

Anyone can fork any of them as the starting point for their own consumer. The repo becomes a *how to build with this* resource, not just a *what this is* resource.

## The argument against over-investing

The temptation is to keep adding centralized smarts to the brain itself — a "brain agent" service that takes natural language and synthesizes answers, a query-rewriting layer, semantic routing, etc. Reject all of that. See [`docs/consumer-integration.md`](./consumer-integration.md) and [intelligence-strategy notes in the conversation log] for why.

The brain stays small and obvious. The intelligence belongs to each consumer (each consumer brings its own LLM and reasons over the brain's outputs in its own domain-specific way). Anything centralized in the middle gets in the way more often than it helps.

The project's value isn't "a smart middleware service." The project's value is **a sharp, opinionated, debugged knowledge substrate, plus the example apps that demonstrate how to consume it.**

## What value the project does NOT have

Being honest about ceiling, so we don't oversell:

- **It's not a new algorithm.** Graphiti's bi-temporal property graph is upstream.
- **It's not a new product category.** Personal knowledge graphs aren't new (Obsidian, Roam, Logseq, Mem, Reflect, etc.).
- **It's not the only self-hostable option.** Hermes Agent, basic-memory, and others occupy similar territory.
- **It's not differentiated by the brain itself.** It's differentiated (if at all) by the opinion that the brain should be a backbone service for many consumer apps, and by the polish of the deploy + integration story.

The project competes on **architectural opinion + operational polish + demonstrated pattern**, not on raw functionality. Treat that as the design constraint.

## Roadmap implications

This framing changes the priority order. From [`plans/phase-1-graph-online.md`](../plans/phase-1-graph-online.md), the most-leverage remaining work is:

1. **First example consumer** (job-fit scorer or similar) — turns "this is a pattern" into "here's the pattern working."
2. **Capture-only PWA** — second example consumer, owns the mobile-capture surface that nothing else can.
3. **One-command self-host** — turns the project from "a debugged deploy" into "a thing anyone can run."
4. **Hosted demo brain** — turns the project from "a thing anyone can run" into "a thing anyone can try in 30 seconds."

Items 1 and 2 are tracked in the current task list. Items 3 and 4 are roadmap-tier and should land before any kind of public launch.

## Alternatives considered

- **Going harder on the daily-driver framing.** If this is purely a tool for the author, none of the self-host / example-app work matters and we'd shrink scope to "ingest + Claude Code consumes it." Decision: keep the daily-driver story AND the broader vision; the example apps serve both because the author also benefits from a job-fit scorer that knows their context.
- **Going commercial.** A hosted version of this with managed brains, billing, etc. could be a small SaaS. Considered, parked — too early to plan for. Revisit only if the self-host story gets real traction.
- **Pure open-source play.** Ship as a reference implementation, no commercial intent. Probably the right framing for now. The self-host script + example consumers are the deliverables.
