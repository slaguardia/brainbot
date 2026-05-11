# Plan: Phase 4 — Hardening + life expansion

## Context

Phases 1–3 stand the system up and make it daily-usable. Phase 4 is open-ended — it's the work that turns "it works" into "it's resilient and worth running for years." Unlike Phases 1–3, this isn't a single weekend's work. It's a backlog of independent tracks, each picked up when the relevant pain point is felt or the relevant entity type has accumulated enough throughput to justify modeling.

**Sequence:** backups first (the only one that's non-negotiable). Everything else: pick by current pain.

**Definition of done for Phase 4:** there isn't one. The phase ends when brainbot stops being the most interesting thing to work on, and the focus shifts elsewhere. The goal here is to leave it in a state where neglect for a month doesn't break it.

This is also the phase where any persistent operational state finally shows up — observability, dedup tracking, backup metadata. None of it existed in Phases 1–3 and it stayed out deliberately. By the time these tasks bite, the actual shape of the data is obvious and you can pick the right store (likely just rotated ndjson files; reach for SQLite or similar only if structured queries are genuinely needed).

---

## Track A — Backups (non-negotiable)

### Task 4.1 — Nightly FalkorDB dump to off-VPS storage

**Choice:** Backblaze B2 (cheapest) or Cloudflare R2 (free egress, ~$0.015/GB-month). Pick R2 for simplicity if Cloudflare is already in the stack.

**New file:** `compose/backup/falkordb-backup.sh`

```
#!/usr/bin/env bash
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T falkordb redis-cli BGSAVE
# wait for BGSAVE complete (LASTSAVE timestamp changes)
sleep 5
docker compose cp falkordb:/data/dump.rdb /tmp/falkor-${TS}.rdb
rclone copy /tmp/falkor-${TS}.rdb r2:brainbot-backups/falkor/
rm /tmp/falkor-${TS}.rdb
# rotation: keep 7 daily, 4 weekly, 12 monthly (rclone filters or a small companion script)
```

**Cron:** systemd timer or `cron` entry: `0 3 * * * /opt/brainbot/compose/backup/falkordb-backup.sh`

### Task 4.2 — Restore-from-backup test (mandatory)

A backup that doesn't restore is worthless. **Once, before declaring backups "done":**

1. Spin up a fresh FalkorDB container locally
2. `rclone copy r2:brainbot-backups/falkor/<latest>.rdb .`
3. Mount the dump into the container's `/data/dump.rdb`
4. Start it, verify graph contents match production (entity counts, sample queries)

Document the procedure in `compose/backup/RESTORE.md`. Future-you needs this.

### Task 4.3 — Backup freshness indicator

Add a tiny "last successful backup: X hours ago" indicator visible somewhere in the PWA (probably a corner of the chat or browse view). Source: the backup script `touch`es a sentinel file on success; the PWA reads its mtime. No database needed.

---

## Track B — Observability

### Task 4.4 — Persistent tool-call logging

When stderr logging from Phase 2 stops being enough (you want to ask "how much did I spend last week?" or "which tool errored most yesterday?"), introduce a persistent log.

Default shape: rotated ndjson files in a mounted volume. One line per tool call. Easy to grep, easy to ship to a real analytics store later if it ever matters. No SQL.

If you genuinely need to ask SQL-shaped questions ("group by tool, p99 latency, last 30 days"), reach for SQLite at *that* point — and put it behind a small interface so the rest of the code doesn't care.

### Task 4.5 — `/admin` route

A SvelteKit route in the PWA that surfaces:
- Recent tool calls (last 24h table)
- Spend over time (per-day cost chart, last 30 days)
- Capture queue depth (if Phase 3's queue is still in use)
- Backup freshness card (Task 4.3)
- Failed extractions (entities Graphiti couldn't extract from the last N episodes)

Reads from whatever Task 4.4 settled on. Auth same as the rest of the PWA.

### Task 4.6 — Cost spike alerting

If today's cost > 3× the trailing 7-day average, send an email (use a simple SMTP relay like Resend or Mailgun, ~free at this volume).

Cheap and prevents a "$200 surprise from a runaway loop."

---

## Track C — Extraction quality maintenance

### Task 4.7 — Weekly dedup audit script

**New file:** `scripts/audit_dedup.py`

Runs weekly via cron. For each entity type:
1. Pull all entities of that type
2. For each pair, compute name similarity (Levenshtein, Jaro-Winkler, embedding cosine — pick one)
3. Flag pairs with similarity > 0.85 as suspicious
4. Write findings somewhere the `/admin` view can read (file, or whatever Task 4.4 settled on)

### Task 4.8 — `/admin/dedup` view

New panel in `/admin/dedup`:
- Side-by-side cards for suspicious pairs
- "Merge into A", "Merge into B", "These are different" buttons
- Merge action calls the same `merge_entities` mutation the Phase 2 browser exposes

This is maintenance work that should take 5 minutes/week if you stay on top of it. Skip a few weeks and the graph degrades.

---

## Track D — Entity types as throughput justifies

**Rule:** don't add new entity types until you have a use case generating data for them. Don't pre-design taxonomy.

Candidates emerge naturally as usage patterns settle. When you notice yourself wanting "show me all things of type X," that's the signal to add `X` as a typed entity. Each one is a few hours of work: define the entity in Graphiti, update relevant tools to populate it, optionally backfill from existing data.

---

## Track E — Fallback memory layer (only if extraction fails)

If the graph noticeably degrades despite hedges (Tasks 4.7 + 4.8 + the Phase 2 browse/edit surface) and queries start missing things they shouldn't:

### Task 4.9 — Add a turn-shaped vector layer alongside the graph

Don't replace the graph — augment it. A vector store of full episode bodies, queried in parallel with Graphiti and unioned in results.

This is the honest fallback. Not a defeat — an admission that some recall is better as semantic search.

**Trigger criteria for pulling this work forward:** if 3+ consecutive "the agent should have known X" incidents trace back to graph fragmentation rather than missing episodes.

---

## Track F — Surface polish

### Task 4.10 — iOS Shortcut polish
- Async confirmation: shortcut returns immediately, sends a follow-up notification when extraction completes ("captured 2 entities: Alice, Acme")
- Multi-language: if traveling, accept dictation in other languages and let Graphiti's extraction handle it

### Task 4.11 — PWA polish
- Offline shell with read-only graph cache (last 100 queries' results cached client-side)
- Dark mode (whatever)
- Search-as-you-type in the chat for past episodes

### Task 4.12 — Apple Watch capture
If the iOS Shortcut is reliable, surface it as a Watch complication. One tap → dictate → captured.

---

## Phase 4 portfolio artifact

Long-form writeup at a public route: `app.{your-domain}/notes/architecture` (a static page served by the PWA, behind no auth).

Audience: senior eng / hiring manager finding it via your job application or Twitter.

Sections:
1. **What this is** — one paragraph, link to GitHub
2. **The bet** — graph vs vector, with the comparison table
3. **The decisions** — Graphiti, FalkorDB, custom harness, MCP-only-for-Claude-Code, graph-canonical with a real editor surface, no second store until you actually need one
4. **What surprised** — extraction cost was lower than expected, latency was higher than expected, Caddy auth was easier than expected, iOS Shortcut was harder than expected (fill in real surprises)
5. **What I'd do differently** — honest section, names 2-3 things
6. **What's next** — multi-graph (work brain vs personal brain)? Shared brain with collaborators (only if life situation changes)? Or — revisit the file-canonical experiment we parked.

This becomes the link in the resume / cover letter / Twitter bio. It's the artifact that proves the project isn't a tutorial.

---

## Risks called out

- **Backup restoration is the only thing that *must* work.** Everything else in Phase 4 is "nice to have." If a single thing in this phase ships, it's Tasks 4.1–4.3.
- **The dedup audit ritual is easy to skip.** If you find yourself skipping 3 weeks in a row, automate the no-brainer cases (e.g., exact-name-match nodes auto-merge) and only surface the genuinely ambiguous ones.
- **Phase 4 has no end state.** That's intentional — it's the maintenance/expansion track. The risk is treating it as "must finish all of this." Pick what hurts. Skip what doesn't.
- **Cost creep over time.** Episode volume grows; extraction cost grows linearly. Watch the `/admin` cost trend monthly. If it crosses a comfort threshold without a corresponding value increase, audit what's being written and tighten the source filters.
- **The persistent-store decision deferred from Phases 1–3 lands here.** Don't reach for the most capable store; reach for the one that fits the actual shape of the data you've accumulated. Files are usually enough.
