// In-process background drainer for brain.pending_episodes. Runs on an
// interval inside the SvelteKit Node server (single-process — no separate
// container needed). Polls for pending rows, calls Graphiti's add_memory MCP
// tool, marks rows done or failed.
//
// Started once via lib/server/init.ts → hooks.server.ts, idempotent.

import { getDb } from './db';
import { addMemory } from './graphiti';
import { env } from './env';

const POLL_INTERVAL_MS = 10_000;
const MAX_ATTEMPTS = 5;
const BATCH_SIZE = 5;

let started = false;

export function startWorker(): void {
  if (started) return;
  started = true;
  console.log('[worker] starting pending-episodes drainer');
  scheduleNext();
}

function scheduleNext() {
  setTimeout(drainOnce, POLL_INTERVAL_MS).unref();
}

async function drainOnce() {
  try {
    if (!env.graphitiUrl) {
      // No graph online; defer.
      scheduleNext();
      return;
    }
    const db = getDb();
    if (!db) {
      scheduleNext();
      return;
    }

    // Claim a batch in a single statement so multiple concurrent drainers
    // (across replicas, if you ever scale out) don't double-process.
    // SKIP LOCKED is the canonical pattern.
    const claim = await db.query(
      `WITH next AS (
         SELECT id FROM brain.pending_episodes
         WHERE status = 'pending' AND attempts < $1
         ORDER BY created_at
         FOR UPDATE SKIP LOCKED
         LIMIT $2
       )
       UPDATE brain.pending_episodes p
       SET status = 'processing',
           attempts = attempts + 1,
           last_attempt_at = now()
       FROM next
       WHERE p.id = next.id
       RETURNING p.id, p.name, p.body, p.source`,
      [MAX_ATTEMPTS, BATCH_SIZE]
    );

    for (const row of claim.rows) {
      try {
        const ok = await addMemory(row.name, row.body, 'text', row.source ?? 'pwa');
        if (ok === null) {
          await db.query(
            `UPDATE brain.pending_episodes
             SET status = 'pending',
                 error_message = 'graphiti_unreachable'
             WHERE id = $1`,
            [row.id]
          );
        } else {
          await db.query(
            `UPDATE brain.pending_episodes
             SET status = 'done', error_message = NULL
             WHERE id = $1`,
            [row.id]
          );
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        // Failed too many times → terminal failed; otherwise back to pending.
        const terminal =
          claim.rows.find((r) => r.id === row.id)?.attempts >= MAX_ATTEMPTS;
        await db.query(
          `UPDATE brain.pending_episodes
           SET status = $2, error_message = $3
           WHERE id = $1`,
          [row.id, terminal ? 'failed' : 'pending', msg]
        );
      }
    }
  } catch (e) {
    console.error('[worker] drain error', e);
  } finally {
    scheduleNext();
  }
}
