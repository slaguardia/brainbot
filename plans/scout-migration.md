# Brief: migrate `scout` onto the brain's graph-sourced facts

**Audience:** an agent working in the **`scout`** repo (`~/Repositories/scout`, Go).
**Author context:** the **brain** (`brainbot`) just shipped "Path A — graph as the
single source of truth." This brief is everything you need to migrate scout's
read path; you should not need the brainbot design conversation.

---

## Goal

Scout currently builds its scoring criteria from the brain's **episode bodies**
(raw captured prose). The brain no longer serves bodies by default — it serves
**structured facts**, each carrying `polarity` and `strength`. Migrate scout to
read facts. One-line success: *scout scores companies off the brain's facts, and
the user's hard gates (location, target verticals, exclusions) are enforced.*

## Why this is needed now (and what's currently broken)

The brain used to return episode bodies because its extracted facts were
positive-only and dropped the user's negatives/gates. That's fixed: negatives and
gates are now first-class facts with `polarity`/`strength`. So the brain retired
the body dump.

**Consequence:** scout's `Criteria()` calls `/profile` and reads `.episodes` —
which is now **absent by default**. So `Bodies()` returns empty, and scout
silently **falls back to local `taste.md`** for every run. It isn't erroring; it's
just no longer using the brain. This migration restores that — and upgrades it.

## The new brain contract (authoritative)

Brain runs at scout's `BRAIN_URL` (locally `http://127.0.0.1:8100`). Verify live:
`curl -s "$BRAIN_URL/profile" | jq` and `curl -s "$BRAIN_URL/recall?q=location&limit=5" | jq`.
Source of truth: `brainbot/brain/brain/api.py` + `service.py`.

**`GET /profile`** — every current fact, flat:
```json
{ "count": 63,
  "facts": [ { "fact": "Steve LaGuardia will only consider roles in the SF Bay Area",
               "polarity": "positive", "strength": "hard",
               "valid_at": "…|null", "name": "ASSERTS" } ] }
```
(Was `{count, episodes:[{name,body,source}]}` — **`episodes` is gone**.)

**`GET /recall?q=&limit=`** — scored facts, no bodies by default:
```json
{ "query": "…",
  "facts": [ { "fact": "…", "name": "ASSERTS", "score": 0.24,
               "polarity": "negative", "strength": "hard",
               "valid_at": "…|null", "invalid_at": "…|null" } ],
  "fact_count": 8 }
```
Pass **`?debug=true`** to additionally get `episodes:[{name,body}]` + `episode_count`
— **debug/provenance only, do NOT build criteria from it.**

**Field semantics** (the whole point):
- `polarity`: `"positive"` (seeks/values/accepts/requires) | `"negative"` (avoids/rejects/excludes) | `null`.
- `strength`: `"hard"` (gate / dealbreaker / requirement) | `"soft"` (preference / lean) | `null`.
- `null` on both = a neutral biographical fact (worked at X, holds clearance, tech stack) — not a stance. Keep it as context, don't treat it as a gate.
- A `negative` + `hard` fact is a **hard exclusion** (→ a `red` driver). A `positive` + `hard` fact is a **hard requirement** (missing it → `red`). `soft` either way is a weight (→ `yellow`).

## What scout does today (the flow you're changing)

```
client.Criteria()  →  GET /profile  →  .Bodies()  →  joined prose string
        │                (empty now → recall fallback → also empty → "")
        ▼
criteria.Resolver  →  taste.Block (cached; falls back to local taste.md if brain empty)
        ▼
verdict.buildSystemPrompt(playbook, taste)  →  injects the criteria text into the LLM scoring prompt
```

**Good news:** everything downstream of `Criteria()` consumes a criteria **string**.
So the migration is mostly **one file** — make `Criteria()` build that string from
**facts** instead of bodies. The Resolver, `taste.Block`, and verdict prompt need
little-to-no change.

## The change — file by file (`~/Repositories/scout`)

### 1. `internal/brainbot/client.go` (the bulk of it)
- **`Fact` struct:** add `Polarity string \`json:"polarity"\`` and `Strength string \`json:"strength"\``. (Both can be empty — graphiti leaves them null on non-stance facts.) Delete the stale comment calling facts "a lossy, POSITIVE-ONLY index" — that's no longer true.
- **`ProfileResult`:** change `Episodes []Episode` → `Facts []Fact` with `json:"facts"`. (Keep `Count`.)
- **`RecallResult`:** `Facts` already there; `Episodes`/`EpisodeCount` are now debug-only — drop them, or gate behind an explicit debug call you don't use for criteria.
- **`Criteria()`:** stop calling `.Bodies()`. Build the criteria string from `pr.Facts` (see formatting below). Drop the `Bodies()` recall-fallback-for-bodies logic; if `/profile` returns zero facts, that's still "brain knows nothing" → return `""` so the caller falls back to `taste.md` (preserve that contract). A `/recall` fallback is no longer needed for criteria (profile already returns all facts).
- **Delete** `Episode`, `ProfileResult.Bodies()`, `RecallResult.Bodies()`, `episodeBodies()` — unless you keep a debug path. Rewrite the now-false comments throughout (esp. lines ~60-99, 148-160).

### 2. Criteria formatting (the design decision)
Render facts into a criteria block the verdict LLM can gate on. Recommended: group
by strength so hard gates are unmistakable. Example:
```
HARD REQUIREMENTS / DEALBREAKERS (treat as gates — a miss is a hard skip):
- [requires] Steve will only consider roles in the SF Bay Area
- [requires] Steve will only consider fully remote roles regardless of HQ
- [excludes] Steve skips all locations requiring onsite or hybrid work
- [excludes] Steve excludes fintech from business/ops platform opportunities
PREFERENCES (weigh, don't gate):
- [seeks] …(soft positive facts)…
- [avoids] …(soft negative facts)…
CONTEXT (background, not a filter):
- …(null/null biographical facts)…
```
Map: `strength=hard` → gates section (split by polarity into requires/excludes);
`soft` → preferences; `null/null` → context. This makes the librarian→scout split
explicit: the brain reports strength; the verdict prompt turns hard→gate, soft→weight.

### 3. `internal/verdict/verdict.go` (light)
`buildSystemPrompt` injects the criteria string as-is, so the new grouped block
flows in for free. Optional upgrade: add one line to the rubric telling the model
that the "HARD" section items are gates (miss → red) and "PREFERENCES" are weights
(miss → yellow). This is where the structured strength actually pays off vs. the
old undifferentiated prose.

### 4. `internal/web/profile.go` (light)
`profilePayload` exposes `cp.Body` (the cached criteria text) for the read-only
view. It keeps working — the cached criteria is now the fact-derived block instead
of body prose. No structural change unless you want to show facts as a list.

## Ordering & safety
- **No brain-side coordination needed** — the brain change is already live and
  deployed (local container, `feat/phase-1-brain-online`). Migrate scout whenever.
- **No data risk** — scout reads the brain read-only. Worst case during dev: it
  falls back to `taste.md` (its existing behavior). Keep that fallback intact.

## Verify (before → after)
1. **Contract:** `curl "$BRAIN_URL/profile" | jq '.facts[0]'` shows `polarity`/`strength`. ✅ before coding.
2. **Criteria:** log `Criteria()` output — confirm it's the grouped fact block, hard gates present (location SF/remote, vertical filter, exclusions).
3. **Verdicts:** re-score the **same** set of postings before and after. Expect the migrated run to correctly **red** anything that violates a hard gate — a non-SF/non-remote onsite role, an off-list vertical (e.g. fintech), an excluded sub-type — where the old `taste.md`-fallback run may have been vaguer. Diff the verdict reasons; they should now cite the specific gate.
4. **Empty-brain path:** point `BRAIN_URL` at nothing / wipe the graph → confirm scout still falls back to `taste.md` cleanly.

## Reference
- Brain contract: `brainbot/brain/brain/api.py`, `brainbot/brain/brain/service.py`.
- Design + rationale: `brainbot/plans/graph-as-source-of-truth.md`, `brainbot/LEARNINGS.md`.
- Scout files: `internal/brainbot/client.go`, `internal/verdict/verdict.go`, `internal/web/profile.go`, `internal/criteria/`.
