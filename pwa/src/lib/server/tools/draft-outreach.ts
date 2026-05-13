import type { Tool } from './types';
import { searchHybrid, searchNodes } from '../graphiti';

interface Input {
  target_company: string;
  target_persona?: string;
  channel?: 'email' | 'linkedin' | 'twitter' | 'other';
  notes?: string;
}

interface Output {
  similar_outreach: unknown;
  company_context: unknown;
  voice_rules_summary: string;
  brief: {
    target_company: string;
    target_persona?: string;
    channel: string;
    notes?: string;
  };
}

// Compound tool: orchestrates three lookups in one model-visible call.
// The model uses the returned brief to actually compose the draft text.

export const draftOutreach: Tool<Input, Output | { error: string; message: string }> = {
  name: 'draft_outreach',
  description:
    'Prepare the materials needed to draft outreach: similar past outreach, the target company, and the user voice rules. Returns a brief; the model composes the actual message text from it.',
  inputSchema: {
    type: 'object',
    properties: {
      target_company: { type: 'string', description: 'Company name.' },
      target_persona: {
        type: 'string',
        description: 'Role, name, or persona of the target (e.g. "founder", "head of growth").'
      },
      channel: {
        type: 'string',
        enum: ['email', 'linkedin', 'twitter', 'other'],
        description: 'Channel (default linkedin).'
      },
      notes: { type: 'string', description: 'Specific angle or facts to weave in.' }
    },
    required: ['target_company']
  },
  handler: async (input) => {
    const channel = input.channel ?? 'linkedin';

    const similar = await searchHybrid(
      `outreach to ${input.target_persona ?? 'founder'} via ${channel}`,
      3
    );
    if (similar === null) {
      return { error: 'brain_offline', message: 'Phase 1 not online.' };
    }

    const company = await searchNodes(input.target_company, 'Company', 1);
    if (company === null) {
      return { error: 'brain_offline', message: 'Phase 1 not online.' };
    }

    // TODO(phase-1): load voice rules from a known set of episode UUIDs
    // (voice.md, my-story.md, outreach-philosophy.md). Cache at boot.
    const voiceRulesSummary =
      'Direct, warm, low-pretense. Short sentences. Avoid "leverage" and "synergy."';

    return {
      similar_outreach: similar,
      company_context: company[0] ?? null,
      voice_rules_summary: voiceRulesSummary,
      brief: {
        target_company: input.target_company,
        target_persona: input.target_persona,
        channel,
        notes: input.notes
      }
    };
  }
};
