import type { Tool } from './types';
import { getDb } from '../db';

interface Input {
  name: string;
  body: string;
  source?: string;
}

// Fire-and-forget queue. MUST NOT block the response on Graphiti's
// 1-3s extraction. We insert a pending row to Postgres and let a background
// worker drain by calling Graphiti's MCP `add_memory` tool.
//
// The worker itself isn't built yet — see brain.pending_episodes migration.

export const addEpisode: Tool<Input, unknown> = {
  name: 'add_episode',
  description:
    "Capture a new piece of information into the user's knowledge graph (a thought, an interaction, a fact, an event). Returns immediately with a queued status; extraction happens asynchronously.",
  inputSchema: {
    type: 'object',
    properties: {
      name: { type: 'string', description: 'Short title for the episode.' },
      body: { type: 'string', description: 'Full text content of the episode.' },
      source: {
        type: 'string',
        description: 'Where this came from (e.g. "chat", "voice", "shortcut"). Defaults to "chat".'
      }
    },
    required: ['name', 'body']
  },
  handler: async (input) => {
    const db = getDb();
    if (!db) return { error: 'db_offline', message: 'Database not reachable.' };
    const res = await db.query(
      `INSERT INTO brain.pending_episodes (name, body, source, status)
       VALUES ($1, $2, $3, 'pending')
       RETURNING id`,
      [input.name, input.body, input.source ?? 'chat']
    );
    return {
      status: 'queued',
      pending_id: res.rows[0].id,
      message: 'Captured. Extraction runs in the background.'
    };
  }
};
