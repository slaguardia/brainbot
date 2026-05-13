// Tool interface used by the chat harness. Compatible with Anthropic's
// tool_use API shape — `definition` is what we ship to the model; `handler`
// is what we run when the model calls it.

export interface Tool<I = unknown, O = unknown> {
  name: string;
  description: string;
  inputSchema: {
    type: 'object';
    properties: Record<string, unknown>;
    required?: string[];
  };
  handler: (input: I, ctx: ToolContext) => Promise<O>;
}

export interface ToolContext {
  sessionId: string;
  model: string;
}

export interface ToolCallRecord {
  toolName: string;
  inputJson: unknown;
  outputJson: unknown;
  status: 'success' | 'error' | 'timeout';
  latencyMs: number;
  errorMessage?: string;
}
