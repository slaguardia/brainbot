// SvelteKit server hooks. Boot-time side effects + per-request auth.

import type { Handle } from '@sveltejs/kit';
import { startWorker } from '$lib/server/worker';
import { isAuthed } from '$lib/server/auth';
import { env } from '$lib/server/env';

let booted = false;

const PUBLIC_PATHS = new Set(['/login']);

export const handle: Handle = async ({ event, resolve }) => {
  if (!booted) {
    booted = true;
    startWorker();
  }

  // Static assets are served before this hook runs (manifest, icons).
  // Apply auth to everything else, but only when PWA_BEARER_TOKEN is set —
  // local dev with no token stays open.
  const path = event.url.pathname;
  if (env.pwaBearer && !PUBLIC_PATHS.has(path)) {
    event.locals.authed = isAuthed(event.request, event.cookies);
    if (!event.locals.authed) {
      return new Response('Unauthorized', { status: 401 });
    }
  } else {
    event.locals.authed = true;
  }

  return resolve(event);
};
