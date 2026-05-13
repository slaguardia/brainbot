// Env access with graceful fallbacks. The PWA must boot even when phase 1
// dependencies (Graphiti, FalkorDB) aren't online — routes return clear
// error responses instead of crashing the process.

export const env = {
  anthropicKey: process.env.ANTHROPIC_API_KEY ?? '',
  anthropicModel: process.env.ANTHROPIC_MODEL ?? 'claude-sonnet-4-6',
  databaseUrl: process.env.DATABASE_URL ?? '',
  graphitiUrl: process.env.GRAPHITI_URL ?? '',
  falkordbUrl: process.env.FALKORDB_URL ?? '',
  pwaBearer: process.env.PWA_BEARER_TOKEN ?? '',
  appDomain: process.env.APP_DOMAIN ?? 'app.localhost',
  groqKey: process.env.GROQ_API_KEY ?? ''
};

export function requireEnv(key: keyof typeof env): string {
  const v = env[key];
  if (!v) throw new Error(`Missing required env: ${key}`);
  return v;
}
