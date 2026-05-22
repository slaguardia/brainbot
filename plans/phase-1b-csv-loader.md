# Plan: Phase 1b — CSV bulk loader (structured data path)

## Context

Graphiti's default ingestion path runs an LLM extraction call on every episode write. That's the right shape for free-text (tweets, journal entries, outreach DMs) but wrong for structured tabular data — Crunchbase exports, application trackers, contact lists. The columns *already* tell you what the entities and relations are; paying Haiku $0.0016/row to re-discover them is wasted spend and slow ingest (a 50k-row Crunchbase export = ~$80 and several hours).

This plan adds a second ingestion path that writes directly to FalkorDB, bypassing Graphiti extraction. The graph stays unified — same node/edge store, same query surface — but structured loads happen via a declarative mapping instead of LLM inference.

**Definition of done:** `python migrate/csv_to_graph.py --mapping mappings/crunchbase.yml --input data/crunchbase_companies.csv` loads 10k rows in under 2 minutes with zero LLM calls, and the resulting nodes are queryable from Claude Code via the same MCP tools as Graphiti-written nodes.

---

## Design

### Two ingestion paths, one graph

```
Free-text episodes ──► Graphiti core ──► (LLM extract) ──► FalkorDB
                                                              ▲
Structured CSVs ────► csv_to_graph ────► (mapping rules) ─────┘
```

Both paths land in the same FalkorDB instance. Queries can't tell the difference. The mapping file is the contract: it declares which columns become node properties, which become edges, and how to dedupe.

### Why a mapping file, not auto-detection

Auto-inferring "this column is a company name, that one is a founder" is exactly the kind of LLM-extraction work we're trying to skip. A 30-line YAML per dataset is faster to write than debugging an LLM that guesses wrong half the time, and it's reusable: re-export Crunchbase next month, same mapping still applies.

---

## Task 1 — Mapping file schema

**New file:** `migrate/mappings/SCHEMA.md` (doc) + example `mappings/crunchbase.yml`

```yaml
# mappings/crunchbase.yml
source: crunchbase_companies
nodes:
  - label: Company
    id_column: uuid           # used for dedup; if absent, hash of (name, domain)
    properties:
      name: name
      domain: homepage_url
      founded: founded_on
      employees: employee_count
      hq_country: country_code
  - label: Person
    id_column: founder_uuid
    when: founder_name is not null
    properties:
      name: founder_name
      linkedin: founder_linkedin
  - label: Industry
    id_column: category_slug   # one node per unique category
    properties:
      name: category_name
edges:
  - type: FOUNDED
    from: Person(founder_uuid)
    to: Company(uuid)
    properties:
      year: founded_on
  - type: IN_INDUSTRY
    from: Company(uuid)
    to: Industry(category_slug)
  - type: BASED_IN
    from: Company(uuid)
    to: Country(country_code)
    properties: {}
```

Rules:
- Each `nodes` entry creates one node per row (subject to `when`). `id_column` is the dedup key — re-running the loader updates existing nodes instead of creating duplicates.
- Each `edges` entry creates one edge per row referencing already-loaded nodes by `(label, id_column)`.
- Vector embeddings are computed for node `name` + concatenated text fields by default (configurable per node type). This keeps hybrid retrieval working — structured nodes are still findable via semantic search.

---

## Task 2 — Loader implementation

**New file:** `migrate/csv_to_graph.py`

Core loop:

```python
def load(mapping_path: Path, csv_path: Path, dry_run: bool):
    mapping = yaml.safe_load(mapping_path.read_text())
    falkor = FalkorDB(host="falkordb", port=6379).select_graph("brain")

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for batch in batched(reader, size=500):
            upsert_nodes(falkor, mapping["nodes"], batch, dry_run)
            upsert_edges(falkor, mapping["edges"], batch, dry_run)

    log_load(mapping["source"], csv_path, rows_loaded)
```

Key behaviors:
- **Batched MERGE.** Use FalkorDB's Cypher `UNWIND $rows AS row MERGE (n:Company {uuid: row.uuid}) SET n += row.props`. ~500 rows per round-trip.
- **Idempotent.** Same MERGE pattern means re-running with the same CSV is a no-op. Re-running with an updated CSV updates fields in place.
- **Embeddings batched separately.** After node upsert, collect nodes that need embeddings, call OpenAI/Voyage in batches of 100, write back. This is the only LLM-ish cost path and it's cheap (~$0.02 per 10k rows with `text-embedding-3-small`).
- **Progress + cost log.** Print rows/sec, total embedding cost. Crunchbase loads should land in the 2-3 minute, <$0.50 range.

---

## Task 3 — Idempotency log (reuse the migration_log pattern)

Extend the table from Phase 1 Workstream B:

```sql
ALTER TABLE brain.migration_log
  ADD COLUMN row_hash TEXT,
  ADD COLUMN load_kind TEXT NOT NULL DEFAULT 'graphiti';
  -- load_kind in ('graphiti', 'csv')
```

CSV loads record one row per (source, row_id, row_hash). On re-run:
- Same hash → skip
- Different hash → re-MERGE (FalkorDB SET overwrites props)
- Missing row in current CSV but present in log → optionally archive (configurable; default leave it)

---

## Task 4 — Verify query parity with Graphiti-written nodes

This is the test that matters: a CSV-loaded `Company` node should be indistinguishable from a Graphiti-extracted one at query time.

**Smoke tests:**
1. Load 100 rows from a Crunchbase sample
2. From Claude Code, ask `mcp__graphiti__search_nodes("AI startups founded after 2023")` — should return CSV-loaded companies
3. Hybrid retrieval check: ask `mcp__graphiti__search_facts("which founders previously worked at Stripe")` — graph traversal should hit CSV-loaded `FOUNDED` edges
4. Free-text episode + CSV cross-reference: write a journal episode mentioning a CSV-loaded company by name → Graphiti's entity dedup should link to the existing CSV-loaded node, not create a duplicate. **This is the critical test.** If it fails, the entity dedup hint config needs adjustment.

---

## Task 5 — Crunchbase-specific mapping

**New file:** `migrate/mappings/crunchbase.yml` (the example above, fleshed out against an actual export)

Variants likely needed:
- `crunchbase_companies.yml`
- `crunchbase_funding_rounds.yml` (creates `FundingRound` nodes + `RAISED` edges)
- `crunchbase_people.yml`

Load order matters: companies → people → funding rounds (edges need both endpoints to exist).

---

## Risks called out

- **Schema drift on re-export.** Crunchbase changes column names. Mapping file should fail loudly on unknown/missing columns rather than silently drop data. Add a `--strict` flag (default on).
- **Entity dedup across paths.** A `Company` node created by CSV has properties `{name, domain, uuid}`. When Graphiti later extracts "Acme" from a tweet, will it match by name? Verify in Task 4 smoke test #4. If not, may need to seed Graphiti's entity index manually after CSV load.
- **FalkorDB memory.** 50k Crunchbase companies + relations is fine on the 2GB cap. 500k+ rows would push it. Monitor `INFO memory` after big loads.

---

## What this unlocks

Once this lands, the workflow for any tabular data (Crunchbase, LinkedIn exports, scraped lists, Notion DB exports) is:

1. Drop CSV in `data/`
2. Write or copy a mapping file (~30 lines)
3. `python migrate/csv_to_graph.py --mapping ... --input ...`
4. Query from Claude Code immediately

No LLM extraction cost, no waiting hours for ingest, structured queries available the moment the load finishes.
