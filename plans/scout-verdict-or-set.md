# Brief: fix scout's verdict gate logic for hard OR-sets

**Audience:** an agent in the **`scout`** repo (`~/Repositories/scout`, Go).
Self-contained — you don't need the brainbot design conversation.

## The problem (one sentence)

Scout's verdict rubric treats **every** HARD requirement as an independent
AND-gate ("a miss forces red"), but the user's **target verticals are an
OR-set** — a company qualifies if it's in *any one* of them — so genuinely good
companies get wrongly red-flagged for "missing" the verticals they were never
meant to match.

## How the criteria flow works (so you know what NOT to touch)

Scout reads the brain's `GET /profile` — a flat list of facts, each with
`polarity` ∈ {`positive`,`negative`,`""`} and `strength` ∈ {`hard`,`soft`,`""`}.
`renderFacts` (`internal/brainbot/client.go`) groups them into a text block:

- **HARD REQUIREMENTS / DEALBREAKERS** — `strength=hard`; positive → `[requires]`, negative → `[excludes]`
- **PREFERENCES** — soft (or polarity-only)
- **CONTEXT** — neutral biographical facts

`buildSystemPrompt` (`internal/verdict/verdict.go`, ~line 277) then wraps that
block with a one-sentence gate rubric, and an LLM scores each company
green/yellow/red.

## The bug, concretely

The HARD section mixes two logically different kinds of `[requires]`:

1. **An OR-set of target domains/verticals** (business/ops platforms,
   defense/govtech, healthcare-ops, AI-agent-platforms) — qualify on domain if
   in **any one**.
2. **Standalone gates** (e.g. location: "SF Bay Area or fully remote").

The current rubric line is:

> `Items under "HARD REQUIREMENTS / DEALBREAKERS" are gates: a miss forces "no" (red). Items under "PREFERENCES" are weights: a miss leans "maybe" (yellow), never an automatic "no".`

"A miss forces red" applied to the OR-set is wrong: no company is in *all* the
verticals, so every company misses most of them → forced red. A real defense
startup matches `[requires] defense or govtech` but misses `[requires] business
and operations platforms`, `[requires] healthcare operations software`,
`[requires] AI agent platforms` → wrongly red.

## The fix

Replace that single rubric sentence in `buildSystemPrompt` with a block that
distinguishes the three logics. Starting-point text (tune to house style):

```
Items under "HARD REQUIREMENTS / DEALBREAKERS" are gates — apply them with this logic:
• [excludes] items are independent dealbreakers: if the company matches ANY one, the verdict is "no" (red).
• [requires] items that name a target market, domain, or vertical are ALTERNATIVES: the company
  only needs to match ONE of them. Matching none of the target domains is "no" (red); failing to
  match the others is expected and is NOT a strike.
• any other [requires] item (e.g. location / work arrangement) is an independent gate that must hold on its own.
Items under "PREFERENCES" are weights: a miss leans "maybe" (yellow), never an automatic "no".
```

## Constraints (read these — they prevent wrong fixes)

- **Consumer-side only. Do NOT change or expect changes from the brain.** The
  brain deliberately returns each target domain as a separate "will only
  consider X" fact (to preserve each member's hardness); inferring they form an
  OR-set is scout's job. This is the intended "brain reports facts / scout
  reasons" split.
- **Do NOT make `renderFacts` mechanically separate "domain requires" from
  "location requires."** Both are `polarity=positive, strength=hard` with no
  field distinguishing them — the distinction is semantic, so it belongs in the
  LLM-facing prompt prose, not Go grouping logic. **Fix the prompt, not
  `renderFacts`.**
- **Check `playbook.md`** (the operator-editable rubric that supersedes the
  builtin) for conflicting gate language; if it restates "every hard item is a
  gate," update it consistently.
- **Verdicts are cached by `taste_version`.** This change is to the
  rubric/system-prompt, likely *not* folded into that hash, so existing verdicts
  won't auto-re-score — use the `Force` re-score path to observe the effect.

## Verify

1. `go build ./...`
2. Force re-score a small known set:
   - a company in **one** target vertical (e.g. healthcare-ops or defense) → must **not** be red just for missing the other verticals
   - an **excluded** category (e.g. fintech) → red
   - a company in **none** of the target domains, not otherwise excluded → red (missed the domain gate)
   - a non-SF, non-remote onsite role → red (location gate)
3. Diff verdict **reasons** before/after: a target-vertical company's reason
   should cite the domain it matched, not "missed business/ops."

**Success:** scout stops red-flagging a company solely for failing to match
*every* target vertical; matching any one target domain (no dealbreaker hit,
location satisfied) keeps it eligible for green/yellow.

## Out of scope

Cosmetic near-dup noise in the facts (e.g. "healthcare-ops" and "biotech" as two
near-identical lines) is expected and harmless — the LLM tolerates it. Don't
build fact-merging.

## Reference

- Brain contract: `brainbot/brain/brain/api.py`, `brainbot/brain/brain/service.py`.
- The prior scout migration (episode-bodies → facts): `brainbot/plans/scout-migration.md`.
- Scout files to touch: `internal/verdict/verdict.go` (the fix), `internal/web/` + `playbook.md` (check for conflicting gate language).
