import type { Tool } from './types';
import { getDb } from '../db';

interface SaveInput {
  target_company?: string;
  target_persona?: string;
  channel?: string;
  subject?: string;
  body: string;
}

export const saveDraft: Tool<SaveInput, unknown> = {
  name: 'save_draft',
  description:
    "Save a draft of outreach so the user can review and send later. Drafts live in app state, not the graph — they're promoted to a graph episode only when marked sent.",
  inputSchema: {
    type: 'object',
    properties: {
      target_company: { type: 'string' },
      target_persona: { type: 'string' },
      channel: { type: 'string' },
      subject: { type: 'string' },
      body: { type: 'string', description: 'Full draft text.' }
    },
    required: ['body']
  },
  handler: async (input) => {
    const db = getDb();
    if (!db) return { error: 'db_offline', message: 'Database not reachable.' };
    const res = await db.query(
      `INSERT INTO brain.drafts (target_company, target_persona, channel, subject, body)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, created_at`,
      [
        input.target_company ?? null,
        input.target_persona ?? null,
        input.channel ?? null,
        input.subject ?? null,
        input.body
      ]
    );
    return { draft_id: res.rows[0].id, created_at: res.rows[0].created_at };
  }
};

interface ListInput {
  company?: string;
  limit?: number;
}

export const listDrafts: Tool<ListInput, unknown> = {
  name: 'list_drafts',
  description: 'List unsent drafts, optionally filtered by company.',
  inputSchema: {
    type: 'object',
    properties: {
      company: { type: 'string', description: 'Filter by target company (substring match).' },
      limit: { type: 'number', description: 'Max results (default 20).' }
    }
  },
  handler: async (input) => {
    const db = getDb();
    if (!db) return { error: 'db_offline', message: 'Database not reachable.' };
    const limit = input.limit ?? 20;
    const res = input.company
      ? await db.query(
          `SELECT id, created_at, target_company, target_persona, channel, subject, body
           FROM brain.drafts
           WHERE sent_at IS NULL AND target_company ILIKE $1
           ORDER BY created_at DESC LIMIT $2`,
          [`%${input.company}%`, limit]
        )
      : await db.query(
          `SELECT id, created_at, target_company, target_persona, channel, subject, body
           FROM brain.drafts
           WHERE sent_at IS NULL
           ORDER BY created_at DESC LIMIT $1`,
          [limit]
        );
    return { drafts: res.rows };
  }
};
