#!/usr/bin/env node
// Tiny SQL migration runner. Applies *.sql files in migrations/ in lexical
// order, idempotently. Tracks applied files in brain.schema_migrations.
//
// Usage: DATABASE_URL=postgres://... npm run migrate
//
// When migrations cross ~10 files or we need rollbacks, swap this for
// node-pg-migrate. The track table is named to be compatible.

import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import pg from 'pg';

const __dirname = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS_DIR = join(__dirname, '..', 'migrations');

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error('DATABASE_URL not set');
    process.exit(1);
  }

  const client = new pg.Client({ connectionString: url });
  await client.connect();

  try {
    // Bootstrap: the schema_migrations table itself may not exist on a fresh
    // DB. The first migration creates `brain` schema; we ensure the tracking
    // table exists right after that.
    const files = (await readdir(MIGRATIONS_DIR)).filter((f) => f.endsWith('.sql')).sort();
    if (files.length === 0) {
      console.log('No migration files found.');
      return;
    }

    // Run the bootstrap (schema + tracking table) outside transactions so we
    // can record application of subsequent files.
    let bootstrapped = false;
    let applied = new Set();

    for (const file of files) {
      const sql = await readFile(join(MIGRATIONS_DIR, file), 'utf8');

      if (!bootstrapped) {
        // The very first file creates the schema. We run it unconditionally
        // (IF NOT EXISTS makes it safe), then create the tracking table if
        // it doesn't exist, then load applied set.
        await client.query(sql);
        await client.query(`
          CREATE TABLE IF NOT EXISTS brain.schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
          )
        `);
        const res = await client.query(
          `SELECT filename FROM brain.schema_migrations`
        );
        applied = new Set(res.rows.map((r) => r.filename));
        await client.query(
          `INSERT INTO brain.schema_migrations (filename) VALUES ($1) ON CONFLICT DO NOTHING`,
          [file]
        );
        applied.add(file);
        bootstrapped = true;
        console.log(`✓ ${file}`);
        continue;
      }

      if (applied.has(file)) {
        console.log(`- ${file} (already applied)`);
        continue;
      }

      await client.query('BEGIN');
      try {
        await client.query(sql);
        await client.query(
          `INSERT INTO brain.schema_migrations (filename) VALUES ($1)`,
          [file]
        );
        await client.query('COMMIT');
        console.log(`✓ ${file}`);
      } catch (e) {
        await client.query('ROLLBACK');
        console.error(`✗ ${file}\n${e}`);
        process.exit(1);
      }
    }
  } finally {
    await client.end();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
