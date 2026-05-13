import type { RequestHandler } from './$types';
import { error } from '@sveltejs/kit';
import { anthropic } from '$lib/server/anthropic';
import { env } from '$lib/server/env';
import { SYSTEM_PROMPT } from '$lib/server/system-prompt';
import { TOOLS, TOOL_BY_NAME, toolDefinitions } from '$lib/server/tools/registry';

// SSE chat endpoint. Streams text deltas as `data: {"delta": "..."}`. Tool
// calls are not exposed in the stream yet — when they fire, the route resolves
// them server-side and the resulting text appears in the next message turn.
// A richer client protocol can come later if the UI needs to surface tool-use
// blocks mid-stream.

interface Body {
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  sessionId?: string;
  model?: string;
}

export const POST: RequestHandler = async ({ request }) => {
  if (!env.anthropicKey) {
    throw error(503, 'ANTHROPIC_API_KEY not configured. See .env.example.');
  }

  const body = (await request.json()) as Body;
  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    throw error(400, 'messages[] required');
  }

  const model = body.model ?? env.anthropicModel;
  const sessionId = body.sessionId ?? crypto.randomUUID();
  const client = anthropic();
  void TOOLS;

  const stream = new ReadableStream({
    async start(controller) {
      const send = (obj: unknown) => {
        controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(obj)}\n\n`));
      };

      try {
        // Single-turn streaming for now. Tool-use loop is handled by resolving
        // tool calls server-side between turns; the SDK's `stream` helper
        // properly buffers tool_use blocks across chunks.
        const messages = body.messages.map((m) => ({
          role: m.role,
          content: m.content
        }));

        let turn = 0;
        const MAX_TURNS = 8;

        while (turn < MAX_TURNS) {
          turn++;

          const response = client.messages.stream({
            model,
            max_tokens: 2048,
            system: SYSTEM_PROMPT,
            tools: toolDefinitions(),
            messages
          });

          for await (const event of response) {
            if (
              event.type === 'content_block_delta' &&
              event.delta.type === 'text_delta'
            ) {
              send({ delta: event.delta.text });
            }
          }

          const final = await response.finalMessage();
          const toolUses = final.content.filter((b) => b.type === 'tool_use');
          if (toolUses.length === 0) break;

          // Run all tool calls in parallel; feed results back to the next turn.
          const toolResults = await Promise.all(
            toolUses.map(async (block) => {
              const tool = TOOL_BY_NAME[block.name];
              if (!tool) {
                return {
                  type: 'tool_result' as const,
                  tool_use_id: block.id,
                  content: JSON.stringify({ error: 'unknown_tool' }),
                  is_error: true
                };
              }
              try {
                const out = await tool.handler(block.input as never, {
                  sessionId,
                  model
                });
                return {
                  type: 'tool_result' as const,
                  tool_use_id: block.id,
                  content: JSON.stringify(out)
                };
              } catch (e) {
                return {
                  type: 'tool_result' as const,
                  tool_use_id: block.id,
                  content: JSON.stringify({ error: String(e) }),
                  is_error: true
                };
              }
            })
          );

          messages.push({ role: 'assistant', content: final.content as never });
          messages.push({ role: 'user', content: toolResults as never });
        }

        send('[DONE]');
      } catch (e) {
        send({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        controller.close();
      }
    }
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive'
    }
  });
};
