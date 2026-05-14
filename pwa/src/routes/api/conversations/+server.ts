import type { RequestHandler } from './$types';
import { json, error } from '@sveltejs/kit';
import { createConversation, listConversations } from '$lib/server/conversations';
import { dbHealthy } from '$lib/server/db';

export const GET: RequestHandler = async () => {
  if (!(await dbHealthy())) {
    return json({ conversations: [], connected: false });
  }
  return json({ conversations: await listConversations(), connected: true });
};

export const POST: RequestHandler = async ({ request }) => {
  if (!(await dbHealthy())) {
    throw error(503, 'Database not reachable.');
  }
  const body = (await request.json().catch(() => ({}))) as { title?: string };
  const id = await createConversation(body.title ?? null);
  if (!id) throw error(503, 'Failed to create conversation.');
  return json({ id });
};
