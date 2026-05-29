---
name: test-brain
description: Test the brainbot brain service end-to-end — ingest documents (section-aware), evaluate recall quality and profile faithfulness, smoke-test capture/retrieval, or wipe and re-seed. Use whenever validating the brain after a change, or checking how source data extracts and recalls.
---

# Testing the brain

The brain service (`brain/`) imports graphiti-core directly and exposes capture + recall over HTTP. This skill is how to exercise and evaluate it. Design context lives in `brain/ARCHITECTURE.md` — read it if a result is surprising.

## Stack + prerequisites

```sh
cd compose && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
curl -sS http://127.0.0.1:8100/health      # -> {"ok":true}
```

- Brain is at **http://127.0.0.1:8100** locally (the local overlay maps it). On VPS it's behind Caddy at `brain.api.{domain}` with a bearer.
- Graph `group_id` = `brain`. `BRAIN_USER_NAME` (in `compose/.env`) is who first-person captures are attributed to — confirm it's set, or facts read "the user".

## Interfaces

| Call | What | Notes |
|---|---|---|
| `POST /capture {text}` | decompose → ingest | **slow** (awaited: 1 decompose call + N extraction passes). Returns `{mode, episodes, topic, facts}`. |
| `GET /recall?q=...&limit=N` | scored facts | each fact has `score` = absolute cosine. |
| `GET /profile` | every current fact | bi-temporal: superseded facts excluded. |
| `python3 scripts/reset_brain.py --graph brain --force` | wipe | `--list` shows graphs + node counts. |

MCP face (for Claude Code) is the same ops at `/mcp` (tools `recall`, `capture`, `profile`).

## Gotchas (learned the hard way — don't relearn them)

- **Long / multi-section docs break a single capture.** The decomposer's JSON output exceeds `max_tokens` (2048) and truncates → 400. **Ingest section-by-section** (use `ingest_doc.py` in this skill dir). Auto-chunking is an unbuilt TODO.
- **Extraction drains asynchronously.** `POST /capture` returns after the write is queued, but graphiti's per-episode extraction runs in a background queue (~2–4s each). After ingesting, **wait ~5–10s per capture** before `/recall` or `/profile` reflects everything.
- **Scores are compressed** with the `voyage-3-lite` embedder (~0.35 on-topic, ~0.20 off-topic — not 0.9). Judge by the **relative gap**, not the absolute number. A bigger embedder widens it (deferred).
- **Capture is single-domain by design right now** (career only). If you ingest mixed domains, recall/profile will mix them — that's expected, not a bug (see ARCHITECTURE.md "Scale cliffs").

## Eval flow (quality check with real data)

1. **Wipe** so you start clean: `python3 scripts/reset_brain.py --graph brain --force`
2. **Ingest** the source. To pull a Notion page, fetch it (notion-fetch), save the markdown, then:
   `python3 .claude/skills/test-brain/ingest_doc.py /path/to/doc.md`
   (splits on headings, posts each section, prints per-section fact counts)
3. **Wait** for extraction to drain (~10s × number of sections).
4. **Profile check** — `curl -sS http://127.0.0.1:8100/profile` — eyeball faithfulness:
   - Are the **gates** present (e.g. target verticals, the avoid-list)?
   - Did **high-signal** facts survive (e.g. TS/SCI clearance)?
   - Did preference **strength** survive (dealbreaker vs nice-to-have)?
   - Any **conflation** (two unrelated things merged onto one entity)?
5. **Recall battery** — on-topic queries should score notably higher than an off-topic control:
   ```sh
   curl -sS 'http://127.0.0.1:8100/recall?q=what+stage+of+company&limit=5'
   curl -sS 'http://127.0.0.1:8100/recall?q=what+does+the+user+avoid&limit=5'
   curl -sS 'http://127.0.0.1:8100/recall?q=favorite+pizza+topping&limit=5'   # off-topic control → all low
   ```
6. **Report**: faithfulness, recall separation (on-topic vs control), and any conflation.

## Smoke flow (plumbing check, deterministic)

For "does the pipeline work" rather than "is my data good," use a fixed fixture, not Notion:
1. Wipe. 2. Capture a known short fixture. 3. Wait. 4. `/recall` a query the fixture answers → assert top fact scores well + an unrelated query scores low. 5. `/profile` → assert the fixture's facts are present. 6. Wipe.

(A dedicated `scripts/smoke_brain.py` for the brain service is a TODO — the existing one targets the retired graphiti MCP and does NOT exercise this brain.)
