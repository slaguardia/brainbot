// Conversation + message persistence. Tables defined in
// migrations/005_brain_conversations.sql.

import { getDb } from './db';
import type { ChatMessage, Conversation } from '$lib/types';

export interface MessageRow {
  id: string;
  conversationId: string;
  role: 'user' | 'assistant' | 'system';
  contentJson: ChatMessage['content'];
  createdAt: string;
  inputTokens: number | null;
  outputTokens: number | null;
  model: string | null;
}

/** Create a new conversation; returns its uuid. */
export async function createConversation(title: string | null = null): Promise<string | null> {
  const db = getDb();
  if (!db) return null;
  const res = await db.query(
    `INSERT INTO brain.conversations (title) VALUES ($1) RETURNING id`,
    [title]
  );
  return res.rows[0].id;
}

/** List recent (non-archived) conversations, newest first. */
export async function listConversations(limit = 50): Promise<Conversation[]> {
  const db = getDb();
  if (!db) return [];
  const res = await db.query(
    `SELECT id, title, updated_at
     FROM brain.conversations
     WHERE archived_at IS NULL
     ORDER BY updated_at DESC
     LIMIT $1`,
    [limit]
  );
  return res.rows.map((r) => ({
    id: r.id,
    title: r.title ?? 'Untitled',
    updatedAt: r.updated_at.toISOString()
  }));
}

export async function getConversation(id: string): Promise<{
  conversation: Conversation;
  messages: ChatMessage[];
} | null> {
  const db = getDb();
  if (!db) return null;
  const [convRes, msgRes] = await Promise.all([
    db.query(
      `SELECT id, title, updated_at FROM brain.conversations WHERE id = $1 AND archived_at IS NULL`,
      [id]
    ),
    db.query(
      `SELECT id, role, content_json, created_at
       FROM brain.messages WHERE conversation_id = $1
       ORDER BY created_at ASC`,
      [id]
    )
  ]);
  if (convRes.rows.length === 0) return null;
  return {
    conversation: {
      id: convRes.rows[0].id,
      title: convRes.rows[0].title ?? 'Untitled',
      updatedAt: convRes.rows[0].updated_at.toISOString()
    },
    messages: msgRes.rows.map((r) => ({
      id: r.id,
      role: r.role,
      content: r.content_json,
      createdAt: r.created_at.toISOString()
    }))
  };
}

/** Append a message and bump the conversation's updated_at. */
export async function appendMessage(
  conversationId: string,
  message: Omit<ChatMessage, 'id' | 'createdAt'>,
  meta?: { inputTokens?: number; outputTokens?: number; model?: string }
): Promise<string | null> {
  const db = getDb();
  if (!db) return null;
  const client = await db.connect();
  try {
    await client.query('BEGIN');
    const insRes = await client.query(
      `INSERT INTO brain.messages
        (conversation_id, role, content_json, input_tokens, output_tokens, model)
       VALUES ($1, $2, $3, $4, $5, $6)
       RETURNING id`,
      [
        conversationId,
        message.role,
        message.content,
        meta?.inputTokens ?? null,
        meta?.outputTokens ?? null,
        meta?.model ?? null
      ]
    );
    await client.query(
      `UPDATE brain.conversations SET updated_at = now() WHERE id = $1`,
      [conversationId]
    );

    // Auto-title on first user message: use the first 60 chars of the prompt.
    if (message.role === 'user' && typeof message.content === 'string') {
      await client.query(
        `UPDATE brain.conversations
         SET title = $1
         WHERE id = $2 AND title IS NULL`,
        [message.content.slice(0, 60), conversationId]
      );
    }

    await client.query('COMMIT');
    return insRes.rows[0].id;
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

/** Soft-delete (archive). Restorable. */
export async function archiveConversation(id: string): Promise<boolean> {
  const db = getDb();
  if (!db) return false;
  const res = await db.query(
    `UPDATE brain.conversations SET archived_at = now() WHERE id = $1 AND archived_at IS NULL`,
    [id]
  );
  return (res.rowCount ?? 0) > 0;
}
