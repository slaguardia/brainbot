// Wraps every tool with logging to brain.tool_calls. One-line change per
// tool, complete coverage. Best-effort — instrumentation failures never block
// the tool itself.

import type { Tool, ToolContext } from './types';
import { getDb } from '../db';

export function instrument<I, O>(tool: Tool<I, O>): Tool<I, O> {
  return {
    ...tool,
    handler: async (input: I, ctx: ToolContext) => {
      const start = Date.now();
      let status: 'success' | 'error' | 'timeout' = 'success';
      let output: O | undefined;
      let errorMessage: string | undefined;

      try {
        output = await tool.handler(input, ctx);
        return output;
      } catch (e) {
        status = 'error';
        errorMessage = e instanceof Error ? e.message : String(e);
        throw e;
      } finally {
        const db = getDb();
        if (db) {
          const latencyMs = Date.now() - start;
          // Fire-and-forget — never block the tool response on logging.
          db.query(
            `INSERT INTO brain.tool_calls
               (session_id, tool_name, input_json, output_json, status,
                latency_ms, model, error_message)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
            [
              ctx.sessionId,
              tool.name,
              input,
              output ?? null,
              status,
              latencyMs,
              ctx.model,
              errorMessage ?? null
            ]
          ).catch(() => {
            /* logging failure is not a tool failure */
          });
        }
      }
    }
  };
}
