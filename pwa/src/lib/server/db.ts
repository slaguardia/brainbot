import pg from 'pg';
import { env } from './env';

let pool: pg.Pool | null = null;

export function getDb(): pg.Pool | null {
  if (!env.databaseUrl) return null;
  if (!pool) {
    pool = new pg.Pool({
      connectionString: env.databaseUrl,
      max: 10,
      idleTimeoutMillis: 30_000
    });
  }
  return pool;
}

export async function dbHealthy(): Promise<boolean> {
  const db = getDb();
  if (!db) return false;
  try {
    await db.query('SELECT 1');
    return true;
  } catch {
    return false;
  }
}
