import Anthropic from '@anthropic-ai/sdk';
import { env } from './env';

let client: Anthropic | null = null;

export function anthropic(): Anthropic {
  if (!client) {
    if (!env.anthropicKey) {
      throw new Error('ANTHROPIC_API_KEY is not set');
    }
    client = new Anthropic({ apiKey: env.anthropicKey });
  }
  return client;
}
