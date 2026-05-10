# Plan: Phase 3 — Write-back loop + capture surface polish

## Context

Phase 1 made the brain readable from Claude Code. Phase 2 made it interactive from the PWA. Phase 3 closes the loop: every interaction *feeds* the brain (Claude Code sessions, captured thoughts, voice notes from the phone), and capturing a thought becomes a 2-second action from anywhere. After this phase, the experience of "I told it about X yesterday, why doesn't it know" should not happen.

OpenClaw gets retired in this phase — the PWA quick-capture + iOS Shortcut subsume its capture role.

**Three workstreams, can be parallelized but sequenced for verification:**
1. Claude Code → brain write-back (sessions become episodes)
2. Quick-capture surfaces (PWA screen + iOS Shortcut)
3. OpenClaw decommission

**Definition of done for Phase 3:** capture a thought in the PWA on the train; 30 seconds later, ask about it in Claude Code on the laptop and get a real answer. OpenClaw is no longer running.

---

## Workstream A — Claude Code write-back

### Task 3.1 — `SessionEnd` hook that writes a session summary

**New file:** `~/Repositories/personal/.claude/hooks/write_session_episode.py`

Behavior:
1. Runs at `SessionEnd`
2. Reads the session transcript (Claude Code provides path via env var)
3. Calls Claude Haiku with prompt: "summarize this session in 3-5 sentences focused on what was decided, what was built, what's still open"
4. POSTs the summary to Graphiti as an episode:
   - `name`: `"Session: {first user prompt's first 40 chars} — {date}"`
   - `body`: the summary
   - `entity_hints`: `{"surface": "claude_code", "repo": <cwd basename>}`
5. Logs cost + duration to `.claude/logs/write_session_episode.log`

**Verify:** open a session in `personal/`, do something, close it, then in a new session ask "what did I work on yesterday in this repo?" — should pull back the summary.

### Task 3.2 — Optional: include key file diffs

If the session touched files (Edit/Write tool calls in transcript), include filenames + a one-line diff summary in the episode body. Lets the agent answer "what files did I change?" semantically.

Skip if it adds too much noise to the episode body. First pass: only include filenames, not diffs. Revisit if recall feels thin.

### Task 3.3 — Idempotency / dedup for session episodes

Edge case: hook fires twice (Claude Code crash + restart). Use the session ID (Claude Code provides one) as part of the episode `name` so re-fires update the existing node instead of creating a duplicate.

---

## Workstream B — Quick-capture surfaces

### Task 3.4 — PWA quick-capture screen

**New file:** `pwa/src/routes/capture/+page.svelte`

A single-purpose view, distinct from the full chat:
- One textarea, big, takes most of the screen
- "Capture" button at the bottom
- Optional: tags input (chips) — lets you hint entity types ("met:Alice company:Acme")
- Submit calls `add_episode` directly (not via the chat agent — too slow)
- Returns optimistic success in <100ms; queues the actual Graphiti write

This screen exists because *typing into a chat to remember something is too many steps*. Capture should feel like a notes app.

**Add to PWA manifest:** "shortcuts" array so iOS long-press on the home-screen icon shows "Quick Capture" as a direct entry.

### Task 3.5 — Capture API endpoint (PWA backend)

**New file:** `pwa/src/routes/api/capture/+server.ts`

```
POST /api/capture
Body: { text: string, tags?: string[], source?: string }
Auth: bearer token OR signed cookie
Response 202: { episode_id: string, queued_at: string }
```

Internally calls the same `add_episode` queue as Task 2.6 from Phase 2 — fire-and-forget, optimistic.

### Task 3.6 — iOS Shortcut for voice capture

iOS Shortcuts app config (one-time setup, document in `pwa/docs/ios-shortcut.md`):
1. Trigger: "Hey Siri, capture brain"
2. Step 1: Dictate text (Siri voice-to-text)
3. Step 2: HTTP POST to `https://app.{domain}/api/capture` with `{ text: <dictation>, source: "ios-voice" }` and the bearer header
4. Step 3: Show notification "Captured" or "Failed"

Add to `iCloud Shortcuts` so it's available on iPhone + Apple Watch.

**Verify:** "Hey Siri, capture brain. I had coffee with Alice from Acme today, she mentioned they're hiring an FDE." → check Graphiti minutes later for the episode + entities.

### Task 3.7 — Multi-surface integration test

A scripted manual test, run end-to-end before declaring Phase 3 done:

1. On phone, "Hey Siri, capture brain" → say something with a unique marker (e.g. "tested phase 3 with codeword zorbax")
2. Wait 30s
3. On laptop, open Claude Code in `personal/`, ask "what's the latest captured note?"
4. Should see the codeword come back

If it doesn't work, debug in this order: shortcut HTTP failed? PWA capture endpoint returned non-202? `pending_episodes` still has the row stuck? Background worker not draining? Graphiti returned an error?

---

## Workstream C — OpenClaw decommission

### Task 3.8 — Drain checkpoint

Before stopping OpenClaw, confirm no use cases still depend on it:
- Telegram capture: replaced by iOS Shortcut + PWA capture
- Any other automations: audit and migrate or drop

Document the audit findings in `compose/migrations/openclaw-drain.md` (one-time doc, lives in repo for the postmortem).

### Task 3.9 — Stop and remove

```bash
docker compose stop openclaw
docker compose rm openclaw
```

Edit `compose/docker-compose.yml` — delete the `openclaw` service block.

Edit `compose/Caddyfile` — delete any routes pointing to OpenClaw.

`docker compose up -d` to apply.

### Task 3.10 — Archive OpenClaw-related docs

Move `agent-hosting/openclaw-*.md` (in the personal repo) to `agent-hosting/archive/` with a top note: "OpenClaw was decommissioned 2026-XX-XX in favor of brainbot's PWA + iOS capture. Kept for reference."

Free up VPS disk: `docker volume rm openclaw-data` (after confirming no salvageable state).

---

## Phase 3 portfolio artifact

Twitter thread + a short blog post.

**Twitter thread:** "Decommissioning OpenClaw — what worked, what didn't, what I built instead"

Beats:
1. What OpenClaw was supposed to do (capture + light agentic tasks)
2. Why it didn't work for me ("okay at everything, good at nothing" — the original framing)
3. What I built instead (graph + PWA + iOS Shortcut)
4. The 2-second capture-from-anywhere demo (short Loom)
5. Honest tradeoffs — owning the harness means owning the bugs

**Blog post:** longer-form version on personal site, links the OpenClaw bootstrap commit, the brainbot Phase 1 PR, the Phase 3 decommission. Forms a narrative.

This kind of "I tried something, learned, replaced it" content reads as senior. Resist the urge to soften the OpenClaw story — the contrast is the point.

**Discipline:** ship before starting Phase 4.

---

## Risks called out

- **Background worker becomes a single point of failure.** If the Node process crashes mid-drain, queued episodes sit in Postgres forever. Add: a startup pass that drains any `pending_episodes` rows older than 5 minutes, and a `/admin` panel showing queue depth + oldest pending. Both small adds.
- **iOS Shortcut auth.** Storing the bearer token in a Shortcut isn't great (Shortcuts aren't encrypted at rest). Acceptable for personal use; document as a known limitation. A real fix would be a per-device API key with scoped permissions — defer to Phase 4 if it bothers you.
- **Session summaries can be too verbose.** First pass might produce 8-paragraph summaries that flood the graph. Tune the Haiku prompt to enforce 3-5 sentences max with explicit length constraints.
- **OpenClaw rollback.** If decommission breaks something unexpected, the rollback is `docker compose up -d openclaw` *if* the service block is still in the compose file. Keep a tagged commit immediately before Task 3.9 so revert is one git command.
