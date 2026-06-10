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

/**
 * The Tier 0 change signal. `cursor` is the brain's current opaque change stamp
 * (compare for equality only — never parse it); `changed` is whether it differs
 * from the `since` you passed.
 */
export type Change = {
  cursor: string;
  changed: boolean;
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

/**
 * Tier 0 change signal — the current change `cursor` and whether it differs from
 * `since`. One cheap call, no LLM. Use it directly to revalidate a cached view
 * lazily (store the `cursor`, pass it back as `since`, recompute when
 * `changed`); or use {@link onChange} to be called when it moves.
 */
export async function changes(since?: string): Promise<Change> {
  const params = new URLSearchParams();
  if (since !== undefined) params.set("since", since);
  const qs = params.toString();
  return getJson<Change>(`/api/brain/changes${qs ? `?${qs}` : ""}`);
}

/** Options for {@link onChange}. */
export type OnChangeOptions = {
  /** Poll period in ms. Default 60_000 — the brain is human-paced, so a 30–60 s
   *  poll is effectively instant; tune per consumer. */
  intervalMs?: number;
  /** Seed the baseline from a stored cursor (e.g. one persisted last session),
   *  so a change that happened while you were away fires on the first poll.
   *  Omit for a view that is current at subscribe time. */
  since?: string;
};

/**
 * Subscribe to brain content changes. TRANSPORT-AGNOSTIC by design: today this
 * POLLS the Tier 0 cursor ({@link changes}) on an interval; if a push feed
 * (SSE/webhook) is ever added, this swaps to a subscription INSIDE the toolkit
 * and no caller changes — they only ever called `onChange`. That seam is the
 * point: get the event-driven feel now, pay only for polling, defer push.
 *
 * Fires `callback` whenever the brain's content moves (the cursor advances).
 * It establishes a baseline at subscribe time (or from `opts.since`) and fires
 * on every later move — never on the baseline itself. Transient poll failures
 * are swallowed and retried on the next tick (the timer is a fallback ceiling).
 * Returns an unsubscribe function; call it to stop polling.
 */
export function onChange(callback: () => void, opts: OnChangeOptions = {}): () => void {
  const intervalMs = opts.intervalMs ?? 60_000;
  let last = opts.since;
  let baselined = opts.since !== undefined;
  let stopped = false;
  let inFlight = false;

  async function poll(): Promise<void> {
    if (stopped || inFlight) return; // skip if a slow poll is still running
    inFlight = true;
    try {
      const { cursor } = await changes(last);
      if (stopped) return; // unsubscribed mid-fetch: don't baseline or fire into a dead view
      if (!baselined) {
        // First poll with no seed: adopt the current cursor silently — "moved"
        // means moved FROM here, so this isn't a change to report.
        last = cursor;
        baselined = true;
      } else if (cursor !== last) {
        last = cursor;
        callback();
      }
    } catch {
      // Transient failure (brain blip, offline): leave the baseline as-is and
      // let the next tick retry. A real outage surfaces through the consumer's
      // own reads, not here.
    } finally {
      inFlight = false;
    }
  }

  const timer = setInterval(poll, intervalMs);
  void poll(); // kick once so a seeded `since` (or first check) doesn't wait a full interval

  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
