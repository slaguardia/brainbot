/**
 * session — read the signed-in identity. No login UI, no token handling.
 *
 * Auth lives at the edge (oauth2-proxy injects `X-Auth-Request-Email`). The app
 * backend reads that header and echoes it as `GET /api/me → { email }`. This
 * helper consumes that endpoint. When no identity header is present (e.g. local
 * dev with no edge in front), the backend returns no email and this returns
 * null — the app shows an anonymous/dev state, never a login form.
 */

export type CurrentUser = { email: string };

/**
 * Resolve the current user, or null when there is no identity. Treats a 401 or
 * a body without an `email` as "no identity" rather than an error — local dev
 * legitimately has no signed-in user.
 */
export async function currentUser(): Promise<CurrentUser | null> {
  let res: Response;
  try {
    res = await fetch("/api/me", { headers: { Accept: "application/json" } });
  } catch {
    return null;
  }
  if (!res.ok) return null;
  let body: { email?: unknown };
  try {
    body = (await res.json()) as { email?: unknown };
  } catch {
    return null;
  }
  return typeof body.email === "string" && body.email ? { email: body.email } : null;
}
