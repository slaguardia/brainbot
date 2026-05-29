# Plan: Phase 2 add-on — edge auth for the PWA (oauth2-proxy + Google + email whitelist)

## Context

The Phase 2 PWA (`pwa/`) is a one-screen capture surface: vanilla TypeScript + Vite
client, raw `node:http` server (`pwa/src/server/index.ts`), zero runtime deps. It was
protected by a **Caddy-edge bearer token** — the *same* `{$BRAIN_BEARER_TOKEN}` as the
brain API — with the bearer meant to ride in the URL once (`?t=...`) so iOS could install
the icon.

This add-on replaces that with **Sign in with Google + an email whitelist, enforced at
the edge by an `oauth2-proxy` sidecar** — not in the app.

**Host layout** (`BRAIN_DOMAIN=stevenlaguardia.me`):

| Host | Serves | Auth |
| --- | --- | --- |
| `brain.{$BRAIN_DOMAIN}` (brain.stevenlaguardia.me) | the PWA (human capture surface) | Google + whitelist |
| `brain.api.{$BRAIN_DOMAIN}` (brain.api.stevenlaguardia.me) | the brain API | bearer |

The PWA takes the bare `brain.` host; the API moved to `brain.api.`.

### Decisions (locked with the user)

- **Edge auth, not in-app.** An `oauth2-proxy` container sits in front of the PWA; Caddy
  uses `forward_auth` to gate every request on a valid, whitelisted Google session.
  Chosen over in-app `@auth/core` because:
  - **The PWA code doesn't change** (no auth library, no login UI, no Dockerfile/dep
    change). Only a one-line service-worker tweak.
  - **Smaller attack surface** — the app never receives unauthenticated traffic, so
    there's no public shell and no app-held session secret.
  - **The whitelist stays dead simple** — a one-email-per-line file in `compose/`.
  - **Layers cleanly under Tailscale later** (the user plans to run Tailscale on the VPS;
    can then bind Caddy to the tailnet and keep oauth2-proxy as a second layer, or drop
    public exposure entirely).
- **OAuth replaces the bearer on the PWA route only.** `brain.api.{$BRAIN_DOMAIN}` keeps
  its bearer — headless consumers (Claude Code MCP, the hook, the migrator) still need it.

### Definition of done

Open `brain.{domain}` → bounced to Google → **only whitelisted accounts get through** →
land on the existing capture screen → capture works end-to-end. Non-whitelisted Google
accounts are denied by oauth2-proxy and never reach the app. The PWA route no longer uses
a bearer; the brain API route (`brain.api.{domain}`) still does.

---

## Architecture

```
phone ──https──▶ Caddy  (brain.{$BRAIN_DOMAIN})
                  │
                  ├─ /oauth2/*  ──▶ reverse_proxy oauth2-proxy:4180   (sign_in, callback, auth, static)
                  │
                  └─ everything else:
                       forward_auth ──▶ oauth2-proxy:4180 /oauth2/auth
                          ├─ 202  (authenticated + whitelisted) ──▶ reverse_proxy pwa:8787
                          └─ 401  ──▶ redir /oauth2/sign_in  ──▶ Google OIDC

brain.api.{$BRAIN_DOMAIN} ──▶ unchanged (Bearer at the edge)
```

oauth2-proxy talks Google OIDC, validates the email against the whitelist file, and sets
its own HttpOnly/Secure session cookie. After login it redirects back to the originally
requested URL, which now passes `forward_auth` and is proxied to the PWA.

---

## Tasks

> Everything below is in `compose/` + docs. **The only `pwa/` change is one line in the
> service worker.** No new npm dependency, no Dockerfile change, no client/server code.

### A. `oauth2-proxy` service — `compose/docker-compose.yml`

Add a service on the `brainnet` network (no host port; only Caddy reaches it):

```yaml
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:latest
    container_name: oauth2-proxy
    restart: unless-stopped
    networks: [brainnet]
    command:
      - --http-address=0.0.0.0:4180
      - --reverse-proxy=true
      - --provider=google
      - --authenticated-emails-file=/etc/oauth2-proxy/emails.txt   # the whitelist
      - --upstream=static://202        # forward_auth mode: no real upstream needed
      - --cookie-secure=true
      - --set-xauthrequest=true        # expose X-Auth-Request-Email to Caddy copy_headers
      - --skip-provider-button=true    # go straight to Google (single provider)
      - --whitelist-domain=brain.${BRAIN_DOMAIN}
    environment:
      OAUTH2_PROXY_CLIENT_ID: ${GOOGLE_OAUTH_CLIENT_ID}
      OAUTH2_PROXY_CLIENT_SECRET: ${GOOGLE_OAUTH_CLIENT_SECRET}
      OAUTH2_PROXY_COOKIE_SECRET: ${OAUTH2_PROXY_COOKIE_SECRET}
      OAUTH2_PROXY_REDIRECT_URL: https://brain.${BRAIN_DOMAIN}/oauth2/callback
    volumes:
      - ./oauth2-proxy-emails.txt:/etc/oauth2-proxy/emails.txt:ro
```

**Whitelist note:** with `--authenticated-emails-file` set and `--email-domain` left
unset, **only** the emails in the file are authorized. Do *not* add `--email-domain=*` —
that would OR-in "any Google account" and defeat the whitelist. Edit the file + restart
oauth2-proxy to change who's allowed.

### B. Caddyfile — `compose/Caddyfile`

Move the PWA onto the bare `brain.{$BRAIN_DOMAIN}` host (drop the bearer; add the
oauth2-proxy route + `forward_auth`), and move the brain API to `brain.api.{$BRAIN_DOMAIN}`.
Per Caddy's `forward_auth` recipe for oauth2-proxy:

```caddy
brain.{$BRAIN_DOMAIN} {
    # oauth2-proxy's own routes: /oauth2/sign_in, /callback, /auth, static assets
    reverse_proxy /oauth2/* oauth2-proxy:4180

    # Gate everything else on a valid, whitelisted Google session.
    forward_auth oauth2-proxy:4180 {
        uri /oauth2/auth
        copy_headers X-Auth-Request-Email X-Auth-Request-User
        @bad status 401
        handle_response @bad {
            redir * /oauth2/sign_in?rd={scheme}://{host}{uri}
        }
    }

    reverse_proxy pwa:8787
}
```

The brain API vhost is renamed `brain.{$BRAIN_DOMAIN}` → `brain.api.{$BRAIN_DOMAIN}`
(bearer + handlers otherwise unchanged). Replace the obsolete bearer-in-URL comment block
with a short note that the PWA is now Google-auth'd via oauth2-proxy.

### C. Whitelist + secrets — `compose/.env.example` + emails file

- `compose/.env.example`: add a PWA-auth block —
  - `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (from Google Cloud, Task D)
  - `OAUTH2_PROXY_COOKIE_SECRET` (note: generate with
    `openssl rand -base64 32` → must decode to 16/24/32 bytes)
  - Keep `BRAIN_BEARER_TOKEN` (still used by the brain route).
- `compose/oauth2-proxy-emails.txt.example` (new): one whitelisted email per line, with a
  comment header. Copied to `compose/oauth2-proxy-emails.txt` (the real, untracked list).
- `.gitignore`: ignore `compose/oauth2-proxy-emails.txt` (it's the live allow-list; keep
  only the `.example` tracked). `.env` is already ignored.

### D. Google Cloud OAuth client (manual, user-run)

Create an OAuth 2.0 Client ID (type: **Web application**) in Google Cloud Console:
- **Authorized redirect URI:** `https://brain.{domain}/oauth2/callback`
  (i.e. `https://brain.stevenlaguardia.me/oauth2/callback`)
- Configure the OAuth consent screen (External, add yourself as a test user, or publish).
- Drop the client id/secret into `compose/.env`.

(No localhost redirect needed — see Task F, local dev skips auth entirely.)

### E. Service worker — `pwa/public/sw.js`

One line: extend the bypass at line 40 so `/oauth2/*` is never cached (alongside the
existing `/api/` bypass), so login redirects/callbacks always hit the network:

```js
if (req.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/oauth2/")) return;
```

### F. Local dev story

Auth is now purely an edge/deploy concern — there's **no auth code in the app**. So local
dev is unchanged and unauthenticated: `npm run dev` (client :5173 → server :8787), exactly
as today. oauth2-proxy only exists in the compose/VPS deployment. (If you ever want to
exercise the full auth path locally, run the whole compose stack with a localhost Google
client + `http://localhost/oauth2/callback`; not needed for normal dev.)

### G. Docs sweep

- `pwa/README.md`: "Known gaps" → replace the "Bearer in URL on first visit" bullet with
  the Google sign-in (oauth2-proxy) flow; update the iOS-install note (first launch
  bounces through Google once, then the cookie persists).
- `plans/phase-2-pwa-harness.md`: rewrite AC #11 ("Bearer at the edge") → unauthenticated
  request to `brain.{domain}` redirects to Google; non-whitelisted account is denied;
  whitelisted account reaches the app and `POST /api/capture` → 202. AC #13 ("no secrets
  in client bundle") still holds and is now trivially true (secrets live only in
  oauth2-proxy's env). Update the §2.4 / Risks bearer notes.
- `architecture.md`: Auth row (~line 158) and open-question #4 (~line 220, cookie auth) →
  note "Google OIDC + email whitelist at the edge via oauth2-proxy" as the resolution.
  Light touch (that doc is partly stale).

---

## Acceptance criteria (observable)

1. `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://brain.{domain}/` →
   `302` redirecting to `/oauth2/sign_in` (or Google). Nothing in the app is reachable
   unauthenticated.
2. `curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://brain.{domain}/api/capture` →
   `302`/`401` (gated), never `202`.
3. A **non-whitelisted** Google account completes Google login but oauth2-proxy denies it
   (403 / "not authorized") — it never reaches the PWA.
4. A **whitelisted** account → lands on the capture screen → type → Send → `202` and the
   episode appears in FalkorDB Browser.
5. `brain.api.{domain}` still returns `401` without the bearer and `200` with it.
6. `docker compose config` validates; oauth2-proxy has **no** host port published
   (`docker compose ps` shows it only on `brainnet`).
7. SW: `/oauth2/*` and `/api/*` are never served from cache; the capture shell still
   loads offline once cached.

---

## Risks / notes

- **Cookie expiry vs. optimistic capture.** When the oauth2-proxy session expires, a
  background `POST /api/capture` gets a redirect/401 instead of `202`; the existing client
  `.catch` path shows "send failed — retry," and a page reload re-auths via Google. Set a
  long cookie lifetime (`--cookie-expire`, e.g. several weeks) to make this rare. Good
  enough for single-user; no app change needed.
- **`forward_auth` directive ordering** in Caddy can be finicky — validate with
  `caddy validate`/`docker compose config` and a real login before trusting it.
- **Tailscale later (option 3).** Independent of this. Once `tailscaled` is on the VPS you
  can bind the `app` vhost to the tailnet interface (drop public exposure) and keep
  oauth2-proxy as defense-in-depth, or expose nothing publicly at all. Doing edge auth now
  doesn't block it.
