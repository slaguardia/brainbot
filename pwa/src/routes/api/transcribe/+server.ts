import type { RequestHandler } from './$types';
import { error, json } from '@sveltejs/kit';
import { env } from '$lib/server/env';

// Voice transcription endpoint — Tier 2 (D6).
// Accepts multipart form data with `audio` field (webm/mp4/wav).
// Returns `{ text: string }`.
//
// Default backend: Groq Whisper-large-v3 (fast, cheap).
// Falls back to "not configured" if GROQ_API_KEY is unset.
//
// The PWA UI should hide the mic button entirely when GROQ_API_KEY is unset,
// so this 503 only fires if someone POSTs directly.

export const POST: RequestHandler = async ({ request }) => {
  if (!env.groqKey) {
    throw error(503, 'Transcription not configured (GROQ_API_KEY unset).');
  }

  const form = await request.formData();
  const audio = form.get('audio');
  if (!(audio instanceof File)) {
    throw error(400, 'audio file required');
  }

  const upstream = new FormData();
  upstream.append('file', audio);
  upstream.append('model', 'whisper-large-v3');
  upstream.append('response_format', 'json');

  const res = await fetch('https://api.groq.com/openai/v1/audio/transcriptions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.groqKey}` },
    body: upstream
  });

  if (!res.ok) {
    const errText = await res.text();
    throw error(502, `Transcription failed: ${errText}`);
  }

  const data = (await res.json()) as { text: string };
  return json({ text: data.text });
};
