// Direct FalkorDB driver used by /api/graph/neighborhood for graph viz.
// We bypass Graphiti for this because Graphiti's REST doesn't expose
// "give me a subgraph centered on X" — FalkorDB does, via Cypher.
//
// Phase-1-blocked: FalkorDB isn't reachable until compose runs. Returns null
// when offline and the route returns 503.

import { env } from './env';
import type { Neighborhood } from '$lib/types';

// FalkorDB driver is a Redis-module client. We don't add the dep until phase 1
// is ready to wire this end-to-end; placeholder shape only.
//
// When wiring, the dep is:  `npm i falkordb`
// then:
//   import { FalkorDB } from 'falkordb';
//   const client = await FalkorDB.connect({ url: env.falkordbUrl });
//   const graph = client.selectGraph('graphiti');
//   const result = await graph.query(cypher, params);

export async function neighborhood(
  nodeId: string,
  depth = 2,
  limit = 50
): Promise<Neighborhood | null> {
  if (!env.falkordbUrl) return null;
  void nodeId;
  void depth;
  void limit;

  // TODO(phase-1): add `falkordb` to deps, replace this stub with:
  //   const cypher = `
  //     MATCH (n {uuid: $id})-[r*1..${depth}]-(m)
  //     RETURN n, r, m LIMIT ${limit}
  //   `;
  //   const result = await graph.query(cypher, { params: { id: nodeId } });
  //   ...shape into { nodes, edges }
  return null;
}
