// Cookie-based session for browsing the PWA on a phone. The flow:
//   1. User visits https://app.example.com/login?token=<bearer>
//   2. Server compares to PWA_BEARER_TOKEN; on match, sets a signed
//      __Host-session cookie for 30 days
//   3. Subsequent requests authenticate via either the cookie OR a
//      Bearer header (API clients keep the header)
//
// Signing key derives from PWA_BEARER_TOKEN itself — rotating the bearer
// invalidates all existing cookies, which is the desired behavior.

import { createHmac, timingSafeEqual } from 'node:crypto';
import { env } from './env';

const COOKIE_NAME = '__Host-session';
const MAX_AGE_S = 30 * 24 * 60 * 60; // 30 days

function signingKey(): string {
  return env.pwaBearer || 'unsigned-development-only';
}

function sign(payload: string): string {
  return createHmac('sha256', signingKey()).update(payload).digest('base64url');
}

export function issueCookie(): string {
  const issued = Math.floor(Date.now() / 1000);
  const expires = issued + MAX_AGE_S;
  const payload = `${issued}.${expires}`;
  const sig = sign(payload);
  return `${payload}.${sig}`;
}

export function verifyCookie(value: string | undefined): boolean {
  if (!value) return false;
  const parts = value.split('.');
  if (parts.length !== 3) return false;
  const [issued, expires, sig] = parts;
  if (!/^\d+$/.test(issued) || !/^\d+$/.test(expires)) return false;
  if (Number(expires) < Math.floor(Date.now() / 1000)) return false;

  const expected = sign(`${issued}.${expires}`);
  // timingSafeEqual requires equal lengths; pad/truncate.
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export function verifyBearer(authHeader: string | null | undefined): boolean {
  if (!env.pwaBearer) return true; // dev mode: no auth required
  if (!authHeader) return false;
  const expected = `Bearer ${env.pwaBearer}`;
  if (authHeader.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(authHeader), Buffer.from(expected));
}

export function isAuthed(request: Request, cookies: { get(name: string): string | undefined }): boolean {
  if (!env.pwaBearer) return true;
  if (verifyBearer(request.headers.get('Authorization'))) return true;
  if (verifyCookie(cookies.get(COOKIE_NAME))) return true;
  return false;
}

export const SESSION_COOKIE_NAME = COOKIE_NAME;
export const SESSION_MAX_AGE_S = MAX_AGE_S;
