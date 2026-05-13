import type { RequestHandler } from './$types';
import { json } from '@sveltejs/kit';
import { env } from '$lib/server/env';
import { dbHealthy } from '$lib/server/db';

export const GET: RequestHandler = async () => {
  const [postgres, graphiti] = await Promise.all([
    dbHealthy(),
    env.graphitiUrl
      ? fetch(`${env.graphitiUrl}/healthcheck`)
          .then((r) => r.ok)
          .catch(() => false)
      : Promise.resolve(false)
  ]);

  return json({
    ok: true,
    services: {
      anthropic: !!env.anthropicKey,
      postgres,
      graphiti,
      falkordb: !!env.falkordbUrl,
      transcription: !!env.groqKey
    }
  });
};
