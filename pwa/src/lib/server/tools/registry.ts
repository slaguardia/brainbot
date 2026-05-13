// Central tool registry. The chat route imports this to build the tools[]
// array passed to Anthropic. Every tool is wrapped in instrument(...) so
// it's logged to brain.tool_calls.

import { instrument } from './instrument';
import { searchBrain } from './search-brain';
import { recallSimilarOutreach } from './recall-outreach';
import { getCompany } from './get-company';
import { addEpisode } from './add-episode';
import { draftOutreach } from './draft-outreach';
import { saveDraft, listDrafts } from './drafts';
import type { Tool } from './types';

// The registry stores tools with erased generics so they're uniformly callable.
// Each handler is invoked with input the model produced, which we trust the
// schema to have validated.
type AnyTool = Tool<any, any>;

export const TOOLS: AnyTool[] = [
  instrument(searchBrain),
  instrument(recallSimilarOutreach),
  instrument(getCompany),
  instrument(addEpisode),
  instrument(draftOutreach),
  instrument(saveDraft),
  instrument(listDrafts)
];

export const TOOL_BY_NAME = Object.fromEntries(TOOLS.map((t) => [t.name, t]));

/** Definitions formatted for Anthropic's tool_use API. */
export function toolDefinitions() {
  return TOOLS.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.inputSchema
  }));
}
