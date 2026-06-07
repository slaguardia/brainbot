/**
 * brain — typed read client for the brain.
 *
 * CRITICAL BOUNDARY: this client talks to the CONSUMING APP's OWN backend at
 * `/api/brain/recall|doc|map`, NEVER to the brain (`brain.api.{domain}`)
 * directly. The bearer token and the brain URL stay server-side in each app's
 * proxy — no secret and no brain origin ever reach the browser. US-003's PWA
 * backend adds these three read-only proxy routes (see consumer-api.md for the
 * shapes the brain returns; this client returns them verbatim, just unwrapped).
 */

/** A recall hit. `id` is the OWNING DOCUMENT's stable id (the doc()/map() key). */
export type Chunk = {
  id: string;
  heading: string;
  text: string;
  score: number;
  path: string;
};

/** A whole document, byte-exact. `version` is the cache key. */
export type Doc = {
  id: string;
  title: string;
  path: string;
  version: string;
  text: string;
};

/** A node in the source tree. `parent_id` null = root OR parent-not-synced. */
export type Source = {
  id: string;
  title: string;
  path: string;
  parent_id: string | null;
  version: string;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { error?: string };
      detail = body.error ? `: ${body.error}` : "";
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`brain ${path} → HTTP ${res.status}${detail}`);
  }
  return (await res.json()) as T;
}

/**
 * Search the brain. Hybrid retrieval; returns top-k chunks (scores reported,
 * not thresholded — the consumer decides relevance). Unwraps `{ chunks }`.
 */
export async function recall(q: string, k?: number): Promise<Chunk[]> {
  const params = new URLSearchParams({ q });
  if (k !== undefined) params.set("k", String(k));
  const body = await getJson<{ chunks: Chunk[] }>(`/api/brain/recall?${params.toString()}`);
  return body.chunks;
}

/** Deterministic whole-document fetch by stable id. */
export async function doc(id: string): Promise<Doc> {
  return getJson<Doc>(`/api/brain/doc?id=${encodeURIComponent(id)}`);
}

/** Discovery: the source tree (ids, versions), ordered by path. Unwraps `{ sources }`. */
export async function map(): Promise<Source[]> {
  const body = await getJson<{ sources: Source[] }>(`/api/brain/map`);
  return body.sources;
}
