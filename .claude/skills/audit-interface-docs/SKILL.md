---
name: audit-interface-docs
description: Audit brainbot's interface docs against the real code and refresh them — the SDK call surface (web-toolkit brain client + brain HTTP/MCP API) and the owner config surface, checking each documented function/endpoint/setting still matches what ships, flagging untrue lines for removal. Use after changing the brain API, the toolkit client, or any owner-facing config; or to spot-check that the interface docs are current.
---

# Auditing the interface docs

Keeps brainbot's **two documented surfaces** honest against the code that
actually ships. The governing rule both surfaces follow is
`docs/configuration-convention.md`:

- **SDK call surface** (developer-facing, intent-only, no knobs): the toolkit
  `brain` client + the brain's HTTP/MCP API.
- **Owner config surface** (owner-facing, per-app prompts/defaults): today only
  the Notion-token connection; the retrieval-chain prompts are *planned* (Direction
  B of `plans/agent-task-support.md`), not yet shipped — so they must NOT be
  documented as if they exist.

This skill is a **maintenance procedure, not a second copy of the docs**: it reads
the code, compares it to the docs, and edits the docs to match — it never invents a
parallel reference.

## Sources of truth (read the CODE, not the docs, for what's real)

| Surface | Code source of truth | Doc(s) it must match |
|---|---|---|
| Toolkit `brain` client | `web-toolkit/src/brain/index.ts` (exported fns + their return types) | `docs/web-toolkit.md` (the `brain` module row + contract sketch) |
| Brain HTTP/MCP API | `brain/api.py` (route handlers, query params, response shapes) | `docs/consumer-api.md` (operations table + per-op shapes), `docs/consumer-integration.md` (narrative) |
| Owner config | the actual settings surface (e.g. PWA `#integrations`, env/DB config the brain reads) | `docs/configuration-convention.md` "realized vs planned" + any future per-app config doc |

## Procedure

1. **Enumerate what ships.** From each code source above, list the real surface:
   every exported toolkit fn and its exact return type; every HTTP route, its query
   params, and its response shape; every owner-settable config and its default.
2. **Enumerate what's documented.** From each doc, list what it *claims* exists.
3. **Diff the two.** Three kinds of drift:
   - **Wrong** — doc states a shape/param/default the code contradicts (e.g.
     `web-toolkit.md` once documented `doc()` as `{text, version}` when the client
     returns the full `{id,title,path,version,text}`). Fix to match code.
   - **Missing** — code ships something the doc omits (e.g. `changes`/`onChange`
     absent from the toolkit surface). Add it.
   - **Stale** — doc describes something the code no longer has, OR documents a
     *planned* feature as if it's live. Remove it (per `feedback_docs_simplicity`:
     dead docs are deleted, not banner'd) or move it to the plan doc as intent.
4. **Apply the fixes** directly to the docs. Match the existing doc's voice and
   table style — this is a refresh, not a rewrite.
5. **Report** what changed, grouped Wrong / Missing / Stale, so the diff is legible.

## Guardrails

- **Code wins.** When a doc and the code disagree, the code is truth; edit the doc.
- **Never document the unbuilt as built.** Planned surfaces (the B retrieval chain,
  its configurable prompts, any not-yet-shipped config) stay in `plans/`, not in the
  current-truth docs. If you find one leaking into a reference doc, that's "Stale —
  move to plan."
- **Don't merge the two audiences.** The SDK reference (developer) and the config
  doc (owner) are separate docs on purpose; keep them separate.
- **No new knobs.** If you find the SDK call surface documenting a per-call
  configuration param (anything beyond intent), that violates the convention —
  flag it loudly rather than documenting it as legitimate.

## Reuse across repos

This skill is a **template**. Its shape (enumerate code → enumerate docs → diff →
fix → report) is identical for any app on the platform (scout, future consumers);
only the "sources of truth" table changes — point it at that repo's client, API,
and config surface. Copy it into the new repo and rewrite only that table.
