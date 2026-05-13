import type { Tool } from './types';
import { searchNodes, getNode } from '../graphiti';

interface Input {
  name: string;
}

export const getCompany: Tool<Input, unknown> = {
  name: 'get_company',
  description:
    "Look up a Company by name and return its 1-hop neighborhood: related people, applications, outreach, and notes. Use when drafting outreach to or analyzing a company's relationship to the user.",
  inputSchema: {
    type: 'object',
    properties: {
      name: { type: 'string', description: 'Company name (case-insensitive).' }
    },
    required: ['name']
  },
  handler: async (input) => {
    const matches = await searchNodes(input.name, 'Company', 1);
    if (matches === null) {
      return { error: 'brain_offline', message: 'Phase 1 not online.' };
    }
    if (matches.length === 0) {
      return { company: null, message: 'No matching company in the brain.' };
    }
    const detail = await getNode(matches[0].uuid);
    return { company: detail };
  }
};
