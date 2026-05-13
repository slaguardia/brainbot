// Anthropic per-token pricing (input/output, USD per 1M tokens). Update when
// new models drop. Used by the instrument wrapper to compute cost_usd for
// each tool call's parent chat turn.
//
// Source: https://www.anthropic.com/pricing — verify before each release.

export interface ModelPrice {
  inputPerMtok: number;
  outputPerMtok: number;
  cacheReadPerMtok?: number;
  cacheWritePerMtok?: number;
}

export const PRICING: Record<string, ModelPrice> = {
  'claude-opus-4-7': {
    inputPerMtok: 15,
    outputPerMtok: 75,
    cacheReadPerMtok: 1.5,
    cacheWritePerMtok: 18.75
  },
  'claude-sonnet-4-6': {
    inputPerMtok: 3,
    outputPerMtok: 15,
    cacheReadPerMtok: 0.3,
    cacheWritePerMtok: 3.75
  },
  'claude-haiku-4-5-20251001': {
    inputPerMtok: 1,
    outputPerMtok: 5,
    cacheReadPerMtok: 0.1,
    cacheWritePerMtok: 1.25
  }
};

export function costFor(
  model: string,
  inputTokens: number,
  outputTokens: number,
  cacheReadTokens = 0,
  cacheWriteTokens = 0
): number {
  const p = PRICING[model];
  if (!p) return 0;
  const fromInput = (inputTokens / 1_000_000) * p.inputPerMtok;
  const fromOutput = (outputTokens / 1_000_000) * p.outputPerMtok;
  const fromCacheRead = ((p.cacheReadPerMtok ?? 0) * cacheReadTokens) / 1_000_000;
  const fromCacheWrite = ((p.cacheWritePerMtok ?? 0) * cacheWriteTokens) / 1_000_000;
  return fromInput + fromOutput + fromCacheRead + fromCacheWrite;
}
