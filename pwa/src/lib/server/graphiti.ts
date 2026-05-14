// MCP JSON-RPC client for Graphiti. Phase 1 ships `zepai/graphiti-mcp`,
// which serves FastMCP at `/mcp/` and no REST surface. Every operation is
// a tools/call invocation against the MCP transport.
//
// Pattern matches migrate/graphiti_clients.py (Python) and
// templates/claude-code-client/inject_memory.py (Python stdlib) in PR #1 —
// keeping the wire format identical avoids surprises.

import { env } from './env';

interface MCPSuccess {
  jsonrpc: '2.0';
  id: string | number;
  result: {
    content?: Array<{ type: string; text?: string }>;
    [k: string]: unknown;
  };
}

interface MCPError {
  jsonrpc: '2.0';
  id: string | number;
  error: { code: number; message: string; data?: unknown };
}

type MCPResponse = MCPSuccess | MCPError;

export interface SearchNode {
  uuid: string;
  name: string;
  summary?: string;
  labels?: string[];
  [k: string]: unknown;
}

export interface SearchFact {
  uuid: string;
  fact: string;
  source_node_uuid?: string;
  target_node_uuid?: string;
  valid_at?: string;
  invalid_at?: string;
  [k: string]: unknown;
}

export interface EntityDetail {
  id: string;
  label: string;
  type: string;
  summary?: string;
  neighbors: Array<{ id: string; label: string; type: string; via: string }>;
}

const GROUP_ID = 'brain';

async function callTool(
  name: string,
  args: Record<string, unknown>,
  timeoutMs = 15_000
): Promise<unknown | null> {
  if (!env.graphitiUrl) return null;

  const url = env.graphitiUrl.replace(/\/$/, '') + '/mcp/';
  const body = JSON.stringify({
    jsonrpc: '2.0',
    id: crypto.randomUUID(),
    method: 'tools/call',
    params: { name, arguments: args }
  });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream'
      },
      body,
      signal: controller.signal
    });
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) return null;

  const contentType = res.headers.get('Content-Type') ?? '';
  const text = await res.text();
  const message = contentType.includes('text/event-stream')
    ? parseSseFinal(text)
    : (safeJson(text) as MCPResponse | null);

  if (!message) return null;
  if ('error' in message) {
    throw new Error(`MCP error: ${message.error.message}`);
  }

  // tools/call wraps the actual tool output in a content[].text JSON string.
  const blocks = message.result.content ?? [];
  for (const block of blocks) {
    if (block.type === 'text' && typeof block.text === 'string') {
      return safeJson(block.text) ?? { text: block.text };
    }
  }
  return message.result;
}

function parseSseFinal(stream: string): MCPResponse | null {
  let last: MCPResponse | null = null;
  for (const line of stream.split('\n')) {
    if (!line.startsWith('data:')) continue;
    const payload = line.slice(5).trim();
    if (!payload || payload === '[DONE]') continue;
    const parsed = safeJson(payload) as MCPResponse | null;
    if (parsed) last = parsed;
  }
  return last;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** Hybrid search across the whole brain. Returns node hits. */
export async function searchNodes(
  query: string,
  maxNodes = 5,
  entityTypes?: string[]
): Promise<SearchNode[] | null> {
  const args: Record<string, unknown> = {
    query,
    group_ids: [GROUP_ID],
    max_nodes: maxNodes
  };
  if (entityTypes && entityTypes.length > 0) args.entity_types = entityTypes;

  const result = await callTool('search_nodes', args);
  if (result === null) return null;
  const obj = result as { nodes?: SearchNode[] };
  return obj.nodes ?? [];
}

/** Fact (edge) search — useful for "what relationships exist around X". */
export async function searchFacts(query: string, maxFacts = 5): Promise<SearchFact[] | null> {
  const result = await callTool('search_memory_facts', {
    query,
    group_ids: [GROUP_ID],
    max_facts: maxFacts
  });
  if (result === null) return null;
  const obj = result as { facts?: SearchFact[] };
  return obj.facts ?? [];
}

/** Ingest a new episode. The MCP tool is named `add_memory` upstream. */
export async function addMemory(
  name: string,
  episodeBody: string,
  source: 'text' | 'json' | 'message' = 'text',
  sourceDescription?: string
): Promise<{ ok: true } | null> {
  const args: Record<string, unknown> = {
    name,
    episode_body: episodeBody,
    group_id: GROUP_ID,
    source
  };
  if (sourceDescription) args.source_description = sourceDescription;
  const result = await callTool('add_memory', args, 30_000);
  return result === null ? null : { ok: true };
}

/**
 * Resolve an entity + its 1-hop neighborhood by uuid into a UI-shaped payload.
 *
 * Implemented over `search_memory_facts` filtered to facts touching the uuid,
 * then enriched with node lookups. Two round-trips; acceptable for entity
 * pages. If this becomes hot, FalkorDB direct Cypher (see falkor.ts) is the
 * faster path.
 */
export async function getEntity(uuid: string): Promise<EntityDetail | null> {
  // Pull facts that mention this node. The MCP server uses uuid as both source
  // and target candidate; we just fetch by node search using its uuid as a query.
  const nodeHits = await searchNodes(uuid, 1);
  if (nodeHits === null) return null;
  const node = nodeHits.find((n) => n.uuid === uuid) ?? nodeHits[0];
  if (!node) return null;

  const facts = await searchFacts(node.name, 20);
  const neighbors: EntityDetail['neighbors'] = [];

  for (const fact of facts ?? []) {
    const otherUuid =
      fact.source_node_uuid && fact.source_node_uuid !== uuid
        ? fact.source_node_uuid
        : fact.target_node_uuid && fact.target_node_uuid !== uuid
          ? fact.target_node_uuid
          : null;
    if (!otherUuid) continue;
    neighbors.push({
      id: otherUuid,
      label: fact.fact.slice(0, 60),
      type: 'edge',
      via: fact.fact
    });
  }

  return {
    id: uuid,
    label: node.name,
    type: (node.labels && node.labels[0]) ?? 'entity',
    summary: node.summary,
    neighbors
  };
}
