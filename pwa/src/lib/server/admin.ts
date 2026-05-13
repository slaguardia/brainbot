import { getDb, dbHealthy } from './db';

export interface AdminMetrics {
  connected: boolean;
  totalCalls: number;
  totalCost: number;
  errorRate: number;
  byTool: Array<{
    name: string;
    count: number;
    p50: number;
    p99: number;
    errors: number;
  }>;
  recent: Array<{
    id: number;
    occurredAt: string;
    toolName: string;
    status: string;
    latencyMs: number;
    costUsd: number | null;
  }>;
}

const EMPTY: AdminMetrics = {
  connected: false,
  totalCalls: 0,
  totalCost: 0,
  errorRate: 0,
  byTool: [],
  recent: []
};

export async function adminMetrics(): Promise<AdminMetrics> {
  if (!(await dbHealthy())) return EMPTY;
  const db = getDb();
  if (!db) return EMPTY;

  try {
    const since = "now() - interval '7 days'";
    const [summary, byTool, recent] = await Promise.all([
      db.query(`
        SELECT
          COUNT(*) AS total_calls,
          COALESCE(SUM(cost_usd), 0)::float AS total_cost,
          COALESCE(AVG(CASE WHEN status='error' THEN 1.0 ELSE 0.0 END), 0)::float AS error_rate
        FROM brain.tool_calls
        WHERE occurred_at >= ${since}
      `),
      db.query(`
        SELECT
          tool_name AS name,
          COUNT(*)::int AS count,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms)::float AS p50,
          PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms)::float AS p99,
          SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)::int AS errors
        FROM brain.tool_calls
        WHERE occurred_at >= ${since}
        GROUP BY tool_name
        ORDER BY count DESC
      `),
      db.query(`
        SELECT id, occurred_at, tool_name, status, latency_ms, cost_usd
        FROM brain.tool_calls
        ORDER BY occurred_at DESC
        LIMIT 50
      `)
    ]);

    return {
      connected: true,
      totalCalls: Number(summary.rows[0].total_calls),
      totalCost: Number(summary.rows[0].total_cost),
      errorRate: Number(summary.rows[0].error_rate),
      byTool: byTool.rows.map((r) => ({
        name: r.name,
        count: r.count,
        p50: r.p50 ?? 0,
        p99: r.p99 ?? 0,
        errors: r.errors
      })),
      recent: recent.rows.map((r) => ({
        id: r.id,
        occurredAt: r.occurred_at.toISOString(),
        toolName: r.tool_name,
        status: r.status,
        latencyMs: r.latency_ms,
        costUsd: r.cost_usd ? Number(r.cost_usd) : null
      }))
    };
  } catch {
    return EMPTY;
  }
}
