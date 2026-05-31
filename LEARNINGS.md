# Brain learnings — an evolution timeline

How the brain's design has actually evolved, chapter by chapter. Unlike
[`docs/`](./docs/README.md) (which describes the system *as it is now* and
discards reversed decisions), this file is **append-only history**: what we
believed, what broke, what we learned, what we changed. Each chapter ends with
the principle it distilled.

The point isn't nostalgia. The brain's value lives in its extraction and
modeling layers, and those layers were *learned*, not designed up front. This is
the story of that learning — and a candidate to surface as the brain's own
"how it got smart" narrative (e.g. in the PWA `#docs` view, alongside release
notes).

> Dates are approximate where the git history doesn't pin them. Chapters are
> ordered, not precisely timestamped.

---

## Chapter 0 — The off-the-shelf MCP server (and why it couldn't hold)

**Believed:** run the published Graphiti MCP server, point clients (Claude Code,
the PWA) at it, done. A standard component, wired up.

**Broke:** the MCP wrapper hid exactly the controls a *personal* brain needs —
extraction overrides, search recipes, entity/edge type definitions. On top of
that, the published image shipped without the provider SDKs, so it silently fell
back to "no LLM configured." We were fighting a black box for the one layer that
matters most.

**Learned:** for a personal brain, **the extraction layer is the product.** A
wrapper that hides extraction can't work, no matter how convenient the protocol.

**Changed:** dropped the standalone MCP server. Built our own small Python
**brain service** that imports `graphiti-core` directly and owns the full
`add_episode` surface. The brain still *speaks* MCP (for Claude Code) — but it's
our service doing it, not someone else's wrapper.

> **Principle:** own the layer that is your value. Don't let a convenience
> wrapper own your extraction.

---

## Chapter 1 — Atomic-fact fan-out (over-atomizing)

**Believed:** the cleaner the input to extraction, the better. So decompose each
capture into many tiny atomic facts and write **one episode per fact** —
maximally unambiguous units.

**Broke:** three ways at once.
- **Rules shattered into instances.** A single location *rule* ("skip anything
  outside the Bay Area") exploded into a pile of individual city nodes — the rule
  itself vanished.
- **Duplication.** The same entity re-extracted across dozens of tiny episodes.
- **Catastrophically slow.** N extraction passes per capture, all awaited.

**Learned:** atomicity is not fidelity. **A rule is a single thing; chopping it
up destroys it.** The unit of capture should be a coherent thought, not a
shredded one.

**Changed:** capture is now **one faithful rewrite → one episode**. An LLM
rewrites the raw text into clean, named-subject, rule-preserving prose; the tuned
extractor pulls facts from that single episode. No fan-out.

> **Principle:** preserve the shape of a thought. Rules stay whole; the extractor
> adapts to the thought, not the thought to the extractor.

---

## Chapter 2 — Teaching the extractor to see concepts

**Believed:** with clean input, graphiti's stock extraction would do the job.

**Broke:** graphiti's default extraction prompt is tuned for Wikipedia-style
named-entity recognition. It *explicitly* refuses abstract concepts — "NEVER
extract abstract concepts," "when in doubt, do NOT extract." For a personal
brain that's exactly backwards: a person's **values, goals, and preferences ARE
the point.** On a real document it pulled ~2 entities and dropped everything that
mattered.

**Learned:** the default extractor's worldview (notability) is the *opposite* of
ours (personal salience). The guiding question isn't "could this have a Wikipedia
article?" but "is this something the owner would want their brain to remember?"

**Changed:** added `custom_extraction_instructions` that override the
conservative defaults and push the extractor to capture concepts, values, goals,
skills, and stances across **any** life domain. Same input went from **2 → 20
entities**.

> **Principle:** a personal brain optimizes for salience, not notability. Tune
> the extractor to the owner's worldview.

---

## Chapter 3 — The lossy-graph patch (where the source of truth quietly drifted)

**Believed:** now that extraction is tuned, the graph holds everything worth
holding. So `profile()` and `recall()` can read straight from the graph — that
was the original plan (`brain/ARCHITECTURE.md`, "Item 2 — full-profile dump from
RELATES_TO facts").

**Broke:** the tuned extractor reliably pulls **positive** facts ("targets X,"
"accepts Y") but **drops negatives and policies**:
- "avoids fintech" — gone.
- "anything outside the allowed set is an automatic skip" — gone.

Proven on the real target-role document: the avoid-list and the vertical gate
were perfectly preserved in the captured episode **body**, but **never became
graph edges.** An edge-only profile silently missed the user's hardest rules.

**Reaction at the time:** patch `profile()` and `recall()` to return the raw
episode **bodies** instead of graph facts — the body is faithful, so completeness
is restored.

**Learned (later — this is the important one):** that patch *worked*, but it
quietly made **the text the source of truth, not the graph.** Every read
bypassed the database the brain exists to be. We had treated a **fixable
extraction/modeling gap** as a **fundamental limit of graphs** — and routed
around our own engine.

> **Principle:** a workaround that bypasses your source of truth is a regression
> wearing a fix's clothes. Notice when "for completeness" means "circumventing
> the database."

---

## Chapter 4 — Graph as the single source of truth (in progress)

**Believe now:** **everything leaving the brain as agent-feeding knowledge must
come from the graph.** If a read bypasses the graph, the database is decorative.
The fix isn't to abandon the graph — it's to make the graph faithful enough to
trust, then read from it.

**The insight that reopened it:** the things the body-dump was covering for are
*not* "graphs can't do this":
- **Negatives** ("avoids X") — graphs handle this fine; we just never *told* the
  extractor to look for negatives. An instruction gap.
- **Strength** (hard gate vs. nice-to-have) — a graph edge can carry this as an
  **attribute**; we just weren't using typed edges. A modeling gap.

Verified that the graphiti we already run supports this: custom `edge_types` with
attributes that are extracted and persisted, via `edge_type_map`.

**Changing (Path A):** tune extraction to capture negatives; add one generic typed
edge carrying `polarity` + `strength`; then rebuild `profile()`/`recall()` to read
from the graph and retire the body-dump. This **returns to the original Item-2
design** — now viable because the graph is finally faithful enough to honor it.
See [`plans/graph-as-source-of-truth.md`](./plans/graph-as-source-of-truth.md).

Kept deliberately **generic** (per [`docs/genericity-rule.md`](./docs/genericity-rule.md)):
`polarity` and `strength` are domain-agnostic dimensions, not career verbs like
"targets/avoids." And we record *how strongly* the user holds something — never
what an app should *do* about it.

> **Principle:** when your store "can't" hold something, check whether you ever
> asked it to. Most "fundamental limits" are untuned defaults. Make the source of
> truth trustworthy instead of routing around it.

### What the design review settled (and the symmetry it exposed)

Working the design out loud sharpened it past the first sketch:

- **"Wall vs. weight" isn't a brain decision — it's the `strength` value.** The
  brain stores how hard the user holds a fact; the *consumer* turns hard→gate,
  soft→weight. That also makes it multi-user for free (your "location = hard" and
  someone else's "location = soft" are the same schema).
- **The consumer is an LLM — so we DON'T over-structure.** No `Constraint` nodes,
  no exception engine, no precedence logic in the brain. Hand an LLM facts +
  strength and it reasons about gates/exceptions/collisions itself. *Everything
  is a fact.* (The "Constraint node" idea from the first sketch died here.)
- **The same "it's an LLM" premise flipped one decision the other way.** For
  storage it *lowered* the bar (reason over loose facts). For `recall`'s old body
  field it *raised* it: an LLM reads any text you put in front of it, so a
  "provenance only, don't use this" label is unenforceable. The body has to
  *leave the payload* (behind a debug flag), not get relabelled.
- **The first real consumer was already built on the bug.** Scout (`~/Repositories/scout`)
  reads episode *bodies* as its criteria *on purpose* — "a scorer built off facts
  alone will pursue companies the user hard-excludes," its own client says. So
  fixing the brain isn't done until the consumer is migrated off bodies — and that
  migration must come *after* the graph is faithful, never before.

> **Principle:** the same premise can cut both ways — "it's an LLM" means *trust
> it to reason* and *don't trust it to ignore*. And a fix isn't finished until the
> consumers built on the old workaround are migrated off it.

---

*Next chapter gets written when this one breaks. It will.*
