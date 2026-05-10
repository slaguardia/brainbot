# Plan: Phase 4 — Hardening + life expansion

## Context

Phases 1–3 stand the system up and make it daily-usable. Phase 4 is open-ended — it's the work that turns "it works" into "it's resilient and worth running for years." Unlike Phases 1–3, this isn't a single weekend's work. It's a backlog of independent tracks, each picked up when the relevant pain point is felt or the relevant entity type has accumulated enough throughput to justify modeling.

**Sequence:** backups first (the only one that's non-negotiable). Everything else: pick by current pain.

**Definition of done for Phase 4:** there isn't one. The phase ends when brainbot stops being the most interesting thing to work on, and the focus shifts to OmniDev or other projects. The goal here is to leave it in a state where neglect for a month doesn't break it.

---

## Track A — Backups (non-negotiable)

### Task 4.1 — Nightly FalkorDB dump to S3-compatible storage

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
# rotate: keep 7 daily, 4 weekly, 12 monthly
rclone delete --min-age 7d --max-age 30d r2:brainbot-backups/falkor/ \
  --include-from <(rclone lsf ... | awk '...')
```

**Cron:** systemd timer or `cron` entry: `0 3 * * * /opt/brainbot/compose/backup/falkordb-backup.sh`

### Task 4.2 — Backup of Postgres `brain` schema

Postgres already gets backed up (assumed Phase 0 work or existing infra). If not, add `pg_dump --schema=brain personal | gzip | rclone rcat r2:brainbot-backups/postgres/brain-${TS}.sql.gz` to the same nightly cron.

### Task 4.3 — Restore-from-backup test (mandatory)

A backup that doesn't restore is worthless. **Once, before declaring backups "done":**

1. Spin up a fresh FalkorDB container locally
2. `rclone copy r2:brainbot-backups/falkor/<latest>.rdb .`
3. Mount the dump into the container's `/data/dump.rdb`
4. Start it, verify graph contents match production (entity counts, sample queries)

Document the procedure in `compose/backup/RESTORE.md`. Future-you needs this.

### Task 4.4 — Backup monitoring

Add to `/admin`: card showing "last successful backup: X hours ago" with red flag if >36h.

Source: write a row to `brain.backup_runs` from the backup script on success.

---

## Track B — Observability extensions

### Task 4.5 — Longer retention + summary tables

`brain.tool_calls` will get large. Three options:
- (a) Drop rows older than 90 days
- (b) Roll up daily aggregates into `brain.tool_calls_daily` and drop raw rows older than 30 days
- (c) Move old rows to a `brain.tool_calls_archive` table

Default: (b). Daily rollups (`tool_name, day, count, p50, p99, total_cost, error_count`) are what `/admin` actually queries; raw rows are only useful for debugging recent issues.

Cron job: nightly rollup script.

### Task 4.6 — Cost spike alerting

If today's cost > 3× the trailing 7-day average, send an email (use a simple SMTP relay like Resend or Mailgun, ~free at this volume).

Cheap and prevents "$200 surprise from a runaway loop."

---

## Track C — Extraction quality maintenance

### Task 4.7 — Weekly dedup audit script

**New file:** `migrate/audit_dedup.py`

Runs weekly via cron. For each entity type:
1. Pull all entities of that type
2. For each pair, compute name similarity (Levenshtein, Jaro-Winkler, embedding cosine — pick one)
3. Flag pairs with similarity > 0.85 as suspicious
4. Write findings to `brain.dedup_candidates` for human review

### Task 4.8 — `/admin` view for dedup candidates

New panel in `/admin/dedup`:
- Side-by-side cards for suspicious pairs
- "Merge into A", "Merge into B", "These are different" buttons
- Merge action calls Graphiti's merge API (if it exists; otherwise: copy edges from B to A, delete B)

This is maintenance work that should take 5 minutes/week if you stay on top of it. Skip a few weeks and the graph degrades.

---

## Track D — Entity types as throughput justifies

**Rule:** don't add new entity types until you have a use case generating data for them. The `feedback_data_before_taxonomy.md` rule cuts hard here.

Candidates, in rough order of likely usefulness:

| Type | When to add |
|---|---|
| `JournalEntry` | When the daily-journal habit is consistent (>20 entries/month for 2+ months) |
| `Tweet` | When the Twitter pipeline is shipping (>10 published/month) |
| `OmniDevFeature` | When OmniDev work is producing structured artifacts worth querying ("show me features tagged 'auth' shipped this quarter") |
| `Book` / `Podcast` | If reading/listening notes become a habit. Might never. |
| `Person` (richer than current) | If networking velocity ramps up — adding fields like "last contact", "preferred channel", "context" |

Each one is a few hours of work: define the entity in Graphiti, update relevant tools to populate it, optionally backfill from existing data.

---

## Track E — Fallback memory layer (only if extraction fails)

If the graph noticeably degrades despite hedges (Tasks 4.7 + 4.8) and queries start missing things they shouldn't:

### Task 4.9 — Add a Hermes-style turn-shaped provider as a second memory layer

Don't replace the graph — augment it. A simple vector store (pgvector on the existing Postgres) of full episode bodies, queried in parallel with Graphiti and unioned in results.

This is the honest fallback. Not a defeat — an admission that some recall is better as semantic search.

**Trigger criteria for pulling this work forward:** if 3+ consecutive "the agent should have known X" incidents trace back to graph fragmentation rather than missing episodes.

---

## Track F — Surface polish

### Task 4.10 — iOS Shortcut polish
- Async confirmation: shortcut returns immediately, sends a follow-up notification when extraction completes ("captured 2 entities: Alice, Acme")
- Multi-language: if traveling, accept dictation in other languages and let Graphiti's extraction handle it

### Task 4.11 — PWA polish
- Offline shell with read-only graph cache (last 100 queries' results cached)
- Dark mode (whatever)
- Search-as-you-type in the chat for past episodes

### Task 4.12 — Apple Watch capture
If the iOS Shortcut is reliable, surface it as a Watch complication. One tap → dictate → captured.

---

## Phase 4 portfolio artifact

Long-form writeup at `brain.{your-domain}/notes/architecture` (a static page served by the PWA, behind no auth).

Audience: senior eng / hiring manager finding it via your job application or Twitter.

Sections:
1. **What this is** — one paragraph, link to GitHub
2. **The bet** — graph vs vector, with the comparison table
3. **The decisions** — Graphiti, FalkorDB, custom harness, MCP-only-for-Claude-Code
4. **What surprised** — extraction cost was lower than expected, latency was higher than expected, Caddy auth was easier than expected, iOS Shortcut was harder than expected
5. **What I'd do differently** — honest section, names 2-3 things
6. **What's next** — OmniDev integration? Multi-graph (work brain vs personal brain)? Shared brain with collaborators (only if life situation changes)?

This becomes the link in the resume / cover letter / Twitter bio. It's the artifact that proves the project isn't a tutorial.

---

## Risks called out

- **Backup restoration is the only thing that *must* work.** Everything else in Phase 4 is "nice to have." If a single thing in this phase ships, it's Tasks 4.1–4.4.
- **The dedup audit ritual is easy to skip.** If you find yourself skipping 3 weeks in a row, automate the no-brainer cases (e.g., exact-name-match nodes auto-merge) and only surface the genuinely ambiguous ones.
- **Phase 4 has no end state.** That's intentional — it's the maintenance/expansion track. The risk is treating it as "must finish all of this." Pick what hurts. Skip what doesn't.
- **Cost creep over time.** Episode volume grows; extraction cost grows linearly. Watch the `/admin` cost trend monthly. If it crosses $20/mo without a corresponding value increase, audit what's being written and tighten the source filters.
