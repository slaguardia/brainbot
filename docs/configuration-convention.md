# Configuration convention

Every app on the platform — **the brain included** — exposes an **owner-facing
config surface for its own prompts and behavior**, ships sensible **defaults**,
and documents it in plain language. The wire *between* apps (the SDK) carries only
**intent**, never configuration.

This is the rule that reconciles two things that look like they conflict: "people
should be able to configure how the brain (and each app) works," and "the SDK
stays knob-free." They don't conflict — they live on two different surfaces, used
by two different people.

## The two surfaces (don't blend them)

| Surface | Who uses it | Form | Carries |
|---|---|---|---|
| **SDK call** | the app *developer* | code — `recall(intent)`, `doc(id)` | intent only, no config |
| **App config** | the *owner/operator* | settings UI / config, per app | that app's own prompts, defaults, behavior |

- **Owner/operator** — the person who deploys and runs an app (for the brain, the
  human it's about). Configures *how their app behaves*, once, globally for their
  deployment.
- **App developer** — whoever writes an app that *calls* another app. Their code
  uses the SDK and passes intent. In a single-user setup these are the same human
  wearing two hats; the moment it's open-source and someone else builds on someone
  else's brain, they're different people. Design for that.

## The pattern, applied per app

Same shape every time:

- **The brain** has retrieval-chain prompts (query decomposition, coverage-judge,
  rerank — see [`../plans/agent-task-support.md`](../plans/agent-task-support.md)).
  Ships defaults. The owner overrides them in *brain* settings.
- **Scout** has its *own* prompts — turning a job posting into the intent it hands
  the brain, and reasoning over the returned chunks into pursue/skip/maybe. Ships
  defaults. The owner overrides them in *scout* settings.
- **Future apps** — their own prompts, their own defaults, their own settings.

**Defaults are mandatory.** An app is fully usable with zero configuration; the
config surface is for owners who want to shape behavior, never a setup tax.

## The clean-wire rule (this is what protects no-knobs)

> **Each app owns and configures its own prompts. The SDK call between apps
> carries only intent, never configuration.**

The test, on three cases:

- Owner tunes **scout's** decision prompt → changes how *scout* reasons. The brain
  never sees it. Scout still calls `recall("...")` plain. ✅
- Owner tunes the **brain's** chain prompt → changes how *the brain* retrieves, for
  every consumer. Scout still calls `recall("...")` plain. ✅
- Scout passes `recall("...", { decompositionPrompt, passes })` → scout reaching
  into the brain's internals on every call. ❌

The third case is the one the no-knobs principle forbids
([`consumer-api.md`](./consumer-api.md), and the `min_score` rejection). Two things
break at once: it's a consumer tuning brain internals, and it destroys the single
eval surface that makes a centralized retrieval chain worth building — if every app
passes its own prompts, there is no longer *one* chain to measure and improve.

"Configure how the brain works" was never what no-knobs forbade. No-knobs governs
the **SDK call surface** only. Owner configuration is a different surface, a
different person, a different column.

## Where this is realized today vs planned

- **Realized:** the brain's owner config surface already exists for *connections* —
  the PWA `#integrations` page where the owner sets the Notion token (DB overrides
  env). Same surface, same audience.
- **Planned:** the brain's *retrieval-chain* prompts become configurable when that
  chain is built (Direction B in
  [`../plans/agent-task-support.md`](../plans/agent-task-support.md)). Scout's prompt
  config is likewise app-side work. This doc states the convention they must follow;
  it does not claim those surfaces exist yet.

## Documentation + the audit skill

Each app keeps **one plain-language doc** of its config surface: what the prompts
are, what they default to, what an owner can change and what that does. Two
audiences means the SDK reference (developer-facing, the call surface) and the
config doc (owner-facing, the knobs) are **separate docs** — don't merge them.

Keeping those docs honest as prompts and defaults drift is a **maintenance
procedure, not a second copy of the docs**: a per-repo skill that audits "does this
app's config doc still match its real prompts and defaults?" and refreshes it. The
skill's *shape* is identical across repos; its *content* (which prompts, which
defaults) differs per app — so it's a template each project instantiates, not one
skill spanning everything.

## How to apply this rule

Adding configurability to an app? Ask: **is this the owner shaping their own app's
behavior, or an app passing configuration across the SDK wire to another?** The
first belongs in that app's config surface with a default. The second is a knob on
the wire — don't build it; the calling app should configure its own behavior
instead.
