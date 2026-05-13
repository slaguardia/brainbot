import type { RequestHandler } from './$types';
import { error, json } from '@sveltejs/kit';
import { neighborhood } from '$lib/server/falkor';

// Subgraph fetch for the Explore tab. Always returns a bounded result —
// never the whole graph.

export const GET: RequestHandler = async ({ url }) => {
  const node = url.searchParams.get('node');
  if (!node) throw error(400, 'node param required');

  const depth = Math.min(parseInt(url.searchParams.get('depth') ?? '2', 10) || 2, 3);
  const limit = Math.min(parseInt(url.searchParams.get('limit') ?? '50', 10) || 50, 200);

  const result = await neighborhood(node, depth, limit);
  if (result === null) {
    throw error(503, 'Graph not online (phase 1 deliverable).');
  }
  return json(result);
};
