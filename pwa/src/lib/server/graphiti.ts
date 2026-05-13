// Graphiti REST client. The Graphiti server isn't online until phase 1 ships;
// every function here returns a clear "phase-1-not-online" failure mode.

import { env } from './env';

export interface GraphitiSearchResult {
  uuid: string;
  name: string;
  type: string;
  summary?: string;
  score?: number;
}

export interface EntityDetail {
  id: string;
  label: string;
  type: string;
  neighbors: Array<{
    id: string;
    label: string;
    type: string;
    via: string;
  }>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  if (!env.graphitiUrl) return null;
  try {
    const res = await fetch(`${env.graphitiUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {})
      }
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export async function searchHybrid(
  query: string,
  limit = 5
): Promise<GraphitiSearchResult[] | null> {
  return call<GraphitiSearchResult[]>(`/search/hybrid`, {
    method: 'POST',
    body: JSON.stringify({ query, limit })
  });
}

export async function searchNodes(
  query: string,
  nodeType: string,
  limit = 5
): Promise<GraphitiSearchResult[] | null> {
  return call<GraphitiSearchResult[]>(`/search/nodes`, {
    method: 'POST',
    body: JSON.stringify({ query, node_type: nodeType, limit })
  });
}

export async function getNode(uuid: string): Promise<unknown | null> {
  return call(`/nodes/${encodeURIComponent(uuid)}`);
}

export async function addEpisode(
  name: string,
  body: string,
  sourceDescription = 'pwa'
): Promise<{ episode_id: string } | null> {
  return call(`/episodes`, {
    method: 'POST',
    body: JSON.stringify({
      name,
      episode_body: body,
      source_description: sourceDescription,
      reference_time: new Date().toISOString()
    })
  });
}

/**
 * Resolve an entity + its 1-hop neighborhood into a UI-shaped payload.
 *
 * NOTE: blocked on phase 1. When Graphiti isn't reachable, returns null and
 * the route renders a "phase-1-not-online" placeholder.
 */
export async function getEntity(id: string): Promise<EntityDetail | null> {
  const node = await getNode(id);
  if (!node) return null;
  // Phase 1 will define the exact response shape; this is a placeholder that
  // returns whatever shape the route can render today.
  const n = node as Record<string, unknown>;
  return {
    id,
    label: String(n.name ?? id),
    type: String(n.type ?? 'entity'),
    neighbors: []
  };
}
