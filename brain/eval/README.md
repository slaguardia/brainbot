# Note-legibility eval (Phase 0/3) — runbook

Decide `legibility.threshold` from **evidence**: "rewrite when health < X *and* it
measurably lifts recall," with X read off a recall@k curve — not guessed. Full
feature + methodology: [`../../docs/note-legibility.md`](../../docs/note-legibility.md).

## Status — can't set X yet (corpus too small)

As of 2026-06-11 the brain has ~6 content sources, only **one** of which is a
genuine headingless dump (Chainguard). The rewrite's benefit is *within-dump chunk
discrimination*, which only becomes measurable when a query about one dump's
sub-idea has to out-rank chunks from **other** overlapping dumps. With one illegible
source, `recall@5` saturates at 1.0 and there's no curve. So **`threshold` stays at
the placeholder `60`** — re-run this eval once there's more data.

A live A/B did show the mechanism working where it could: rewriting Chainguard
lifted that one buried sub-idea's rank from 3rd → 1st (MRR 0.92 → 1.00, precision
+0.22). See the doc's "Eval run" section.

## When is the corpus big enough to set the threshold?

You need enough **topically-overlapping** messy dumps that recall has somewhere to
go wrong — roughly a dozen-plus genuine headingless dumps that share subject matter,
plus a probe set whose queries target *sub-ideas that span multiple dumps* (so the
right chunk has real competition). Signs you're ready: `recall@5` on the baseline is
**below 1.0** (there's headroom), and several dumps score below ~70 on health.

## Step 1 — find the "real dumps" (treatment candidates)

A real dump = a content source the chunker leaves as ONE chunk because it has no
markdown headings (exactly the case the feature targets). Find them:

```sql
SELECT s.id, s.title, length(s.raw_text) AS chars, count(c.id) AS chunks
FROM sources s LEFT JOIN chunks c ON c.source_id = s.id
WHERE length(s.raw_text) > 400
GROUP BY s.id, s.title, s.raw_text
HAVING count(c.id) = 1          -- headingless => collapsed to a single chunk
ORDER BY chars DESC;
```

Pass each id to `run_ab.py --rewrite <id>` (repeatable).

## Step 2 — grow the probe set (`probes.json`)

```json
[{"query": "...", "relevant": ["<source-uuid>", ...], "note": "optional"}]
```

Each probe is a query plus the source id(s) that *genuinely* answer it. The current
set was authored by reading the corpus and **needs expanding + validating as data
grows** — aim queries at sub-ideas that appear inside dumps (the thing a 1-chunk dump
buries), not just whole-source topics. Recall is scored at source granularity (did a
chunk from a relevant source reach the top-k), which is what a consumer escalates on
(recall → `doc(id)`).

## Step 3 — run it

Two harnesses (stdlib + the brain package; no extra deps beyond the brain image):

**`recall_scorecard.py`** — read-only, hits a running brain's HTTP `/recall`. Quick
baseline against the live brain:

```sh
python recall_scorecard.py --brain http://127.0.0.1:8100 --probes probes.json --k 5 \
    --label baseline > baseline.json
```

**`run_ab.py`** — the full isolated A/B (baseline vs treatment) against a **copy** of
the corpus; reads raw_text from a source brain read-only and **never mutates the live
brain**. Needs the real `VOYAGE_API_KEY` + `ANTHROPIC_API_KEY` and an isolated eval
DB. The brain image (`brainbot/brain:0.1`) already has every dep (asyncpg, voyageai,
pgvector, anthropic, the `brain` package), so run it there. Exactly how this was run
on 2026-06-11:

```sh
# 0. secrets (don't echo them): the DB password + keys live in the running stack
PW=$(docker exec postgres printenv POSTGRES_PASSWORD)

# 1. an isolated eval DB (UTF8; run_ab.py creates the pgvector extension itself)
docker exec postgres psql -U brain -d brain \
    -c "CREATE DATABASE brain_eval ENCODING 'UTF8' TEMPLATE template0;"

# 2. run the A/B in a throwaway container on the brain network, keys passed from
#    the running brain's env (command substitution — never printed)
docker run --rm --network compose_brainnet \
    -v "$PWD/../..":/work -w /work/brain/eval -e PYTHONPATH=/work/brain \
    -e VOYAGE_API_KEY="$(docker exec brain printenv VOYAGE_API_KEY)" \
    -e ANTHROPIC_API_KEY="$(docker exec brain printenv ANTHROPIC_API_KEY)" \
    brainbot/brain:0.1 python run_ab.py \
      --source-dsn "postgresql://brain:$PW@postgres:5432/brain" \
      --eval-dsn   "postgresql://brain:$PW@postgres:5432/brain_eval" \
      --probes probes.json --k 5 \
      --rewrite <dump-id-from-step-1>          # repeat --rewrite per dump

# 3. clean up
docker exec postgres psql -U brain -d brain -c "DROP DATABASE IF EXISTS brain_eval;"
```

`run_ab.py` prints the baseline-vs-treatment table, per-probe MRR moves, and each
rewrite (so you can eyeball grounding — it must add no claims). Read the per-health-
dimension deltas to find X: the lowest health score at which the rewrite still
*measurably* lifts recall on held-out probes.

> Network/secret note: `compose_brainnet`, the `brainbot/brain:0.1` image tag, and
> the `postgres`/`brain` container names are this machine's local stack. Adjust for
> another deployment.

## Known follow-up (separate from legibility) — the brain doesn't read DB properties

The brain currently holds ~24 sources with **0-char `raw_text`**. They are NOT junk
stubs — they are rows of a Notion **database** whose real content lives in
**properties** (e.g. a 1001-char `Body` rich_text property), and the brain's ingest
reads page-**body** blocks only, so it captured just the title. Their title-only
embeddings out-rank real content on topical queries and depress baseline recall.

**Don't prune them — the fix is to capture the property text at ingest.** The
Notion migrator (`brain/notion.py`) should, for a database row, fold its rich_text
properties into the ingested content instead of returning an empty body. Doing so
would turn ~24 title-only sources into ~24 real content sources — which also gives
this eval a corpus big enough to actually set the threshold.
