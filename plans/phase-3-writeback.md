# Plan: Phase 3 — Write-back loop + capture surface polish

## Context

Phase 1 made the brain readable from Claude Code. Phase 2 made it interactive from the PWA, with synchronous capture. Phase 3 closes the loop: every interaction *feeds* the brain (Claude Code sessions, captured thoughts, voice notes from the phone), and capturing a thought becomes a 2-second action from anywhere. After this phase, the experience of "I told it about X yesterday, why doesn't it know" should not happen.

This phase is also where the synchronous capture path from Phase 2 grows up — the iOS Shortcut surface needs <100ms response, which forces the introduction of an async write path.

**Two workstreams, can be parallelized but sequenced for verification:**
1. Claude Code → brain write-back (sessions become episodes)
2. Quick-capture surfaces (PWA polish + iOS Shortcut), with the async write path that supports them

**Definition of done for Phase 3:** capture a thought via "Hey Siri" on the phone; 30 seconds later, ask about it in Claude Code on the laptop and get a real answer.

---

## Workstream A — Claude Code write-back

### Task 3.1 — `SessionEnd` hook that writes a session summary

**New file:** `templates/claude-code-client/write_session_episode.py`

Behavior:
1. Runs at `SessionEnd`
2. Reads the session transcript (Claude Code provides path via env var)
3. Calls a small extraction LLM with prompt: "summarize this session in 3-5 sentences focused on what was decided, what was built, what's still open"
4. POSTs the summary to Graphiti as an episode:
   - `name`: `"Session: {first user prompt's first 40 chars} — {date}"`
   - `body`: the summary
   - `entity_hints`: `{"surface": "claude_code", "repo": <cwd basename>}`
5. Logs cost + duration to `.claude/logs/write_session_episode.log`

**Verify:** open a session in any wired-up client repo, do something, close it, then in a new session ask "what did I work on yesterday in this repo?" — should pull back the summary.

### Task 3.2 — Optional: include touched filenames

If the session touched files (Edit/Write tool calls in transcript), include the filename list in the episode body. Don't include diffs in the first pass — too much noise. Revisit if recall feels thin.

### Task 3.3 — Idempotency for session episodes

Edge case: hook fires twice (Claude Code crash + restart). Use the session ID (Claude Code provides one) as part of the episode `name` so re-fires update the existing node instead of creating a duplicate. No external store needed — the deduping happens inside Graphiti by name.

---

## Workstream B — Quick-capture: async write path + iOS Shortcut

### Task 3.4 — In-process async write queue in the PWA backend

**File:** `pwa/src/lib/server/queue.ts`

A simple in-memory FIFO inside the PWA Node process:
- `enqueue(payload)` returns immediately with a synthetic `queue_id`
- A worker loop drains the queue, calling `graphiti add_episode` per payload
- On error: log to stderr and either retry once or drop (TBD by experience)
- On graceful shutdown: drain remaining items before exit

Acceptable failure modes for a single-user system:
- PWA crash mid-drain → captured-but-not-yet-extracted items are lost. If this becomes a real complaint, add a JSON-lines spool file at that point — not before.

### Task 3.5 — `/api/capture` becomes async

**File:** `pwa/src/routes/api/capture/+server.ts`

Change behavior from "block until extraction completes" (Phase 2) to:
1. Validate input
2. `enqueue(payload)`
3. Return 202 with `{ queue_id }` in <100ms

The PWA capture screen still shows a "captured" toast on the 202; the user doesn't notice that extraction completes asynchronously a few seconds later. The chat-side `add_episode` tool stays synchronous so the agent's response can reflect the new episode in the same turn.

### Task 3.6 — PWA quick-capture polish

**File:** `pwa/src/routes/capture/+page.svelte`

Polish pass on the Phase 2 capture screen:
- Optional tags input (chips) — lets you hint entity types ("met:Alice company:Acme")
- Submit calls the new async endpoint; toast appears in <100ms
- Auto-save draft to localStorage on every keystroke; restore on reload (don't lose a thought to a refresh)

**Add to PWA manifest:** "shortcuts" array so iOS long-press on the home-screen icon shows "Quick Capture" as a direct entry.

### Task 3.7 — iOS Shortcut for voice capture

iOS Shortcuts app config (one-time setup, document in `pwa/docs/ios-shortcut.md`):
1. Trigger: "Hey Siri, capture brain"
2. Step 1: Dictate text (Siri voice-to-text)
3. Step 2: HTTP POST to `https://brain.api.{domain}/capture` with `{ text: <dictation>, source: "ios-voice" }` and the bearer header. **Note:** headless capture goes to the **brain API** (bearer-authed), not the PWA host — the PWA is now gated by interactive Google sign-in (oauth2-proxy), which a Shortcut can't complete. See [phase-2-pwa-auth.md](phase-2-pwa-auth.md).
4. Step 3: Show notification "Captured" or "Failed"

Add to iCloud Shortcuts so it's available on iPhone + Apple Watch.

**Verify:** "Hey Siri, capture brain. I had coffee with Alice from Acme today, she mentioned they're hiring an FDE." → check Graphiti minutes later for the episode + entities.

### Task 3.8 — Multi-surface integration test

A scripted manual test, run end-to-end before declaring Phase 3 done:

1. On phone, "Hey Siri, capture brain" → say something with a unique marker (e.g. "tested phase 3 with codeword zorbax")
2. Wait 30s
3. On laptop, open Claude Code in a wired-up client repo, ask "what's the latest captured note?"
4. Should see the codeword come back

If it doesn't work, debug in this order: shortcut HTTP failed? PWA capture endpoint returned non-202? Queue worker drained? Graphiti returned an error?

---

## Phase 3 portfolio artifact

Twitter thread + a short blog post.

**Twitter thread:** "Three capture surfaces, one brain — what worked, what was rough"

Beats:
1. The three surfaces (PWA capture screen, iOS Shortcut/Siri, Claude Code session writes)
2. Why one source of truth matters: the Siri-captured note shows up in the Claude Code session 30 seconds later
3. Honest tradeoffs — owning the harness means owning the bugs; the iOS Shortcut auth situation is real
4. The 2-second capture-from-anywhere demo (short Loom)

**Blog post:** longer-form version on personal site, links the Phase 1 PR, Phase 2 PR, Phase 3 PR. Forms a narrative of the build.

**Discipline:** ship before starting Phase 4.

---

## Risks called out

- **In-memory queue can lose data on crash.** Acceptable for personal use; document as known limitation. The fix (JSON-lines spool file) is small; add it the first time you actually lose something to a crash.
- **iOS Shortcut auth.** Storing the bearer token in a Shortcut isn't great (Shortcuts aren't encrypted at rest). Acceptable for personal use; document as a known limitation. A real fix would be a per-device API key with scoped permissions — defer to Phase 4 if it bothers you.
- **Session summaries can be too verbose.** First pass might produce 8-paragraph summaries that flood the graph. Tune the summarizer prompt to enforce 3-5 sentences max with explicit length constraints.
- **Capture endpoint becomes a write amplifier.** A captured thought is one episode write, but the agent often re-captures the same fact in chat. Watch for episode duplication; if it becomes noise, the dedup audit (Phase 4) catches it.
