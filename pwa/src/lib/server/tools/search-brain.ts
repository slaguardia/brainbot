import type { Tool } from './types';
import { searchNodes, searchFacts } from '../graphiti';

interface Input {
  query: string;
  limit?: number;
}

export const searchBrain: Tool<Input, unknown> = {
  name: 'search_brain',
  description:
    "Search the user's personal knowledge graph (entities and facts) by natural-language query. Returns the most relevant nodes and edges. Use this for any question about people, companies, applications, outreach, or past notes.",
  inputSchema: {
    type: 'object',
    properties: {
      query: { type: 'string', description: 'Natural-language query.' },
      limit: { type: 'number', description: 'Max results per dimension (default 5).' }
    },
    required: ['query']
  },
  handler: async (input) => {
    const limit = input.limit ?? 5;
    const [nodes, facts] = await Promise.all([
      searchNodes(input.query, limit),
      searchFacts(input.query, limit)
    ]);
    if (nodes === null || facts === null) {
      return {
        error: 'brain_offline',
        message:
          'The knowledge graph is not online yet (phase 1 deliverable). Tell the user honestly.'
      };
    }
    return { nodes, facts };
  }
};
