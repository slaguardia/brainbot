# Genericity rule

Brainbot is designed as a **generic shared brain anyone could deploy and use**, not built around the original author's specific situation.

## What this means in practice

Nothing in the core assumes a specific identity, workflow, or pre-existing stack. The system ships with:

- Generic reads (`recall`, `doc`, `map`) that any consumer composes — not workflows baked into the architecture.
- Multiple consumer surfaces (PWA, Claude Code MCP, plain HTTP for your own apps) — no single "primary consumer."
- One default migrator (Notion) treated as *a* source, not *the* source. Other sources (Obsidian, Roam/Logseq, Apple Notes, plain-text journals) are demand-driven siblings. We did *not* pre-build a `migrate/sources/` or `migrate/lib/` structure; that's a refactor the second migrator earns, not preemptive over-design.
- A single persistent store (Postgres + pgvector — see [brain-architecture.md](./brain-architecture.md)) so a downstream user inherits the minimum possible ops surface.
- VPS-vendor-neutral docs — "small VPS" wherever specifics aren't load-bearing.

## What got removed

The original design assumed:

- **Postgres on the VPS** (because an unrelated app was already running there). Cut.
- **An OpenClaw decommission as a phase.** The project no longer assumes any prior agent-hosting stack. Cut.
- **`draft_outreach` / `brain.drafts` / `Outreach` entity / job-hunt context.** Specific workflow built around the original author's job hunt. Replaced with generic tools the agent composes — workflows are things the user discovers, not things the architecture bakes in.
- **iOS Shortcut as the primary capture path.** Demoted to one option among several.
- **Notion as *the* source of seed data.** Reframed as the first migrator, not the only one.

## Why the rule exists

The project is dual-purpose: daily driver and portfolio piece. The portfolio half only works if the architecture defends as a generic system. Burying the author's specific situation in the core makes it look like a personal hack rather than a product.

## How to apply this rule

When adding a feature, ask: would a downstream user with a totally different workflow want this? If the answer is "only if they happen to have my exact setup," it's a personal extension on top of the core, not a core change.
