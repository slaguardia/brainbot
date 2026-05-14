import type { RequestHandler } from './$types';
import { redirect } from '@sveltejs/kit';
import { env } from '$lib/server/env';
import { issueCookie, verifyBearer, SESSION_COOKIE_NAME, SESSION_MAX_AGE_S } from '$lib/server/auth';

// One-time bearer-to-cookie exchange. Visit /login?token=<bearer> on a phone
// once; subsequent browsing uses the signed cookie.
//
// Convenient on a phone (you don't have to set an Authorization header on
// every page request). API clients keep using the header.

export const GET: RequestHandler = async ({ url, cookies }) => {
  if (!env.pwaBearer) {
    // Dev mode: no auth, just bounce to home.
    throw redirect(303, '/');
  }
  const token = url.searchParams.get('token') ?? '';
  if (!verifyBearer(`Bearer ${token}`)) {
    return new Response('Invalid token', { status: 401 });
  }
  cookies.set(SESSION_COOKIE_NAME, issueCookie(), {
    path: '/',
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    maxAge: SESSION_MAX_AGE_S
  });
  throw redirect(303, '/');
};
