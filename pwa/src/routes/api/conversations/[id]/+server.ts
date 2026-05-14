import type { RequestHandler } from './$types';
import { json, error } from '@sveltejs/kit';
import { archiveConversation, getConversation } from '$lib/server/conversations';

export const GET: RequestHandler = async ({ params }) => {
  const result = await getConversation(params.id);
  if (!result) throw error(404, 'Conversation not found.');
  return json(result);
};

export const DELETE: RequestHandler = async ({ params }) => {
  const ok = await archiveConversation(params.id);
  if (!ok) throw error(404, 'Conversation not found.');
  return json({ ok: true });
};
