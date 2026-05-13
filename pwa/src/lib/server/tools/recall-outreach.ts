import type { Tool } from './types';
import { searchNodes } from '../graphiti';

interface Input {
  query: string;
  limit?: number;
}

export const recallSimilarOutreach: Tool<Input, unknown> = {
  name: 'recall_similar_outreach',
  description:
    'Search past Outreach episodes by vector similarity to a query. Returns message body and outcome (responded? hired?). Use when drafting new outreach.',
  inputSchema: {
    type: 'object',
    properties: {
      query: {
        type: 'string',
        description:
          'Description of the outreach you want to find similar examples of (e.g. "cold DM to AI startup founder").'
      },
      limit: { type: 'number', description: 'Max results (default 3).' }
    },
    required: ['query']
  },
  handler: async (input) => {
    const results = await searchNodes(input.query, input.limit ?? 3, ['Outreach']);
    if (results === null) {
      return { error: 'brain_offline', message: 'Phase 1 not online.' };
    }
    return { results };
  }
};
