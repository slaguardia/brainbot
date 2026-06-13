# The app platform — building N apps on the brain

> Companion to [`architecture.md`](./architecture.md). That doc answers "what is
> the brain and how do consumers read it." This one answers the question that
> shows up once you have **more than one** consumer app: *how do I build and ship
> app N+1 without inventing a new stack every time?* It is the missing layer
> between "one brain, many consumers" (the vision) and a pile of divergent apps
> (the risk). Written 2026-06-07.

## The problem this solves

The brain already proved the data layer: one Postgres+pgvector substrate, read
over HTTP by any number of stateless consumers. That part scales — adding a
consumer doesn't touch the brain.

What does **not** scale yet is everything *around* each consumer's UI:

| | brainbot dashboard | scout |
|---|---|---|
| Frontend delivery | separate Vite app, real assets | one 3,920-line `index.html` via `go:embed` |
| Shares design/shell/auth with… | nothing | nothing |
| Edge / auth | Caddy + oauth2-proxy, HTTPS | none, localhost only |
| Installable (PWA) | no (plain web app; the toolkit can add it) | no |

Two apps, two unrelated frontend stacks, two deployment postures. At app three
this becomes the bottleneck. **"Make them all PWAs" is the symptom; the cure is
sharing the layers underneath the PWA.**

## The reframe: PWA is an *outcome*, not the work

A PWA is just a web app that is (a) served over a real HTTPS origin, (b) ships a
web app **manifest**, and (c) registers a **service worker**. The app-like feel
— installable to the home screen, an offline shell — falls out of those three.

So "all apps are PWAs" decomposes into two shared layers every app sits on. Get
these right once and PWA-ness is free for every app, forever:

1. **A shared edge** — gives every app a real HTTPS origin + single sign-on. The
   brain already has this (Caddy + oauth2-proxy). Reuse it; don't rebuild it.
2. **A shared web toolkit** — gives every app the same design system, app shell,
   service worker + manifest, and brain client. This is the **new** piece.

Backends stay **polyglot on purpose** (see below). The shared layers are the
edge and the frontend toolkit — not the runtime.

## The four layers

```
┌──────────────────────────────────────────────────────────────┐
│  L4  apps        scout · reader-triage · calendar-prep · …     │
│                  each: own backend + own PWA, own repo         │
├──────────────────────────────────────────────────────────────┤
│  L3  web toolkit shared package: design tokens, app shell,     │
│                  service-worker + manifest gen, brain client,  │
│                  auth/session helper   ← the missing layer     │
├──────────────────────────────────────────────────────────────┤
│  L2  edge        Caddy + oauth2-proxy: HTTPS + Google SSO,     │
│                  one vhost per app   ← already built (brainbot)│
├──────────────────────────────────────────────────────────────┤
│  L1  substrate   the brain (Postgres + pgvector over HTTP)     │
│                  ← already built, already scales               │
└──────────────────────────────────────────────────────────────┘
```

L1 and L2 exist. L3 is the work. L4 is each app, and each app gets cheaper as L3
matures.

## What an app *is* (the contract)

Standardize the **contract**, not the implementation. An app is:

> A **backend service** that owns its own domain data and talks to the brain over
> HTTP, **+** a **PWA** built from the shared web toolkit, **+** deployed behind
> the shared Caddy edge as one vhost.

Everything an app must satisfy:

- **Owns its own data.** App-specific state (scout's verdicts, a reader queue's
  read/unread) lives in the app's own store. It is *not* in the brain. The brain
  holds cross-app knowledge about *you*; apps hold their own working set. (This
  is already a scout invariant: "verdicts stay scout-local.")
- **Reads the brain read-only over HTTP.** `recall` / `doc` / `map`. Never writes
  back. (See [`consumer-integration.md`](./consumer-integration.md).)
- **Serves a JSON `/api/*`** that its PWA consumes. The backend renders no HTML.
- **Ships a PWA built from the toolkit.** Not a bespoke frontend.
- **Sits behind the edge** as `appname.{domain}`, inheriting HTTPS + SSO.

Nothing in that contract names a language. That's deliberate.

## Backends stay polyglot — do not unify the runtime

Forcing one backend language buys nothing and costs rewrites. The brain is
Python because pgvector + embeddings + asyncpg is its natural home. Scout is Go
because batch ingest→filter→enrich→verdict over SQLite with cheap re-runs is
what Go is good at. A future calendar-prep app might be a 200-line Node service.

What makes them *feel* like one product is **not** a shared runtime — it's:

- the same look (L3 design system),
- the same sign-in (L2 SSO),
- the same data they reason over (L1 brain),
- the same shape (`/api/*` JSON + toolkit PWA).

The unit of sharing is the **contract and the frontend**, not the backend
language. A senior reviewer reads "polyglot backends behind a shared edge and a
shared web toolkit" as deliberate, not as drift.

## App data: two kinds, and where the engines live

The most common confusion when adding apps is "should this go in the brain?" The
answer comes from recognizing there are **two kinds of data**, and they never
mix:

| Kind | Examples | Lives in | Why |
|---|---|---|---|
| **Knowledge about *you*** | preferences, history, what kind of company you want, who you've met | the **brain** (shared, system of record) | it's true across apps and it's *about you*, not about one app's job |
| **An app's working set** | scout's companies/verdicts/runs, a reader queue's read/unread | the **app's own store** (local, disposable) | it's *derived output* of one app — rebuildable, not a fact about you |

**Logical separation is non-negotiable.** An app's working set never goes *into*
the brain's dataset (its `sources`/`chunks`). Scout's verdicts are scout's; the
brain stays read-only for consumers. (This is invariant 1 below, and scout's own
"verdicts stay scout-local.")

**The physical engine is a per-app ops choice — the parallel to polyglot
backends.** Just as runtimes differ per app, so can stores:

- **SQLite for disposable + embedded apps (scout).** Scout's data rebuilds from a
  CSV, so it barely needs backups; SQLite keeps scout a single self-contained,
  run-anywhere, offline-friendly Go binary with zero DB dependency. **Scout stays
  on SQLite even though a Postgres is deployed for the brain** — the reasons are
  disposability (the "we already back up Postgres" benefit is moot for scratch
  state), the single-binary property, and **blast radius** (a consumer app must
  not be able to degrade the brain's database, the thing every app depends on).
- **A dedicated database on the brain's Postgres *server* for durable +
  concurrent apps.** The already-deployed Postgres is a **server** future apps can
  share — but each gets its **own separate database** on it, never a table inside
  the brain's schema. Reach for this only when an app's working set is genuinely
  durable and concurrent (not disposable like scout's).

> **Rule of thumb:** *same server, separate database* is fine for apps that need
> durability; *same dataset as the brain* is never fine. SQLite is the right
> default for a disposable, embedded app; promote to a dedicated Postgres DB only
> when durability/concurrency demands it.

## Frontend shape: separate installable PWAs (decided)

Two options were on the table:

- **One PWA, many tabs** — a single installed shell with an app switcher; apps
  are modules inside it.
- **Separate installable PWAs** — each app is its own installable PWA at its own
  URL, all built from the shared toolkit. ✅ **chosen**

Separate PWAs win here because the repo layout is **separate repos + a shared
package** (decided). A single-shell super-app wants a single repo (or messy
module federation) and couples every app's release to the shell's. Separate PWAs
keep each app independently deployable while still looking and signing in
identically — which is exactly what a multi-repo + shared-package layout is good
at. You install the apps you use; each is `appname.{domain}`.

Consequence: the toolkit must be consumable as a **versioned package**, and
cross-cutting design changes are a package bump per app, not one edit. That's the
accepted tradeoff of multi-repo (see below).

## Repo layout: separate app repos + the toolkit in brainbot (as built)

```
brainbot/
  web-toolkit/   L3 the shared package every PWA depends on (lives here)
  dashboard/           the brainbot dashboard (toolkit consumer)
  + L1 brain + L2 edge config
scout/           L4 app: Go backend + PWA (toolkit consumer)
<app-3>/         L4 app: any backend + PWA (toolkit consumer)
```

- Each **app** stays its own repo with clean boundaries and an independent
  release cycle.
- The **web toolkit lives inside brainbot** (`brainbot/web-toolkit/`), the
  platform hub, rather than as a standalone repo. Apps consume it as a package —
  scout pins it via `"@brainbot/web-toolkit": "file:../../brainbot/web-toolkit"`
  (a git-tag/registry dep is the upgrade path if it ever needs independent
  versioning). This doesn't change how apps are built: they still just depend on
  the package.
- Cost, named honestly: a cross-cutting frontend change (new design token, shell
  fix) means each app picks up the new toolkit version. Acceptable at this scale;
  promote the toolkit to its own repo only if independent release cycles become
  worth it — it's a clean extract.

## L3 — what's in the web toolkit

Harvest it from what brainbot's dashboard already does — it's the natural donor
(vanilla TS + Vite + manifest + service worker already exist). The toolkit is
that, generalized:

| Piece | What it is | Donor |
|---|---|---|
| **Design system** | CSS variables (the dark theme, the verdict colors, spacing/typography scale), base components | brainbot `dashboard/src/style.css` + scout's inline CSS, reconciled |
| **App shell** | the page chrome, nav/header, view-routing convention, loading/empty/error states | brainbot `dashboard/src/main.ts` hash router |
| **PWA plumbing** | `manifest.webmanifest` generator (per-app name/icon/theme) + a standard `sw.js` (offline shell + asset cache) | brainbot `dashboard/public/` |
| **Brain client** | typed `recall()` / `doc()` / `map()` over HTTP, with the auth header handled | brainbot `dashboard/src/server` proxy logic |
| **Session/auth helper** | reads the identity oauth2-proxy injects at the edge; no per-app login code | brainbot edge contract |
| **Build preset** | a shared Vite config so every app builds the same way | brainbot `dashboard/vite.config.ts` |

Stay vanilla TS + Vite (no React/Vue). It's what both apps already are, it keeps
the toolkit tiny, and it's a defensible "no framework tax" story. Revisit only if
an app's UI genuinely outgrows it.

## L2 — the shared edge (already built)

brainbot's `compose/` already has the whole pattern: Caddy (Let's Encrypt HTTPS)
+ oauth2-proxy (Google OIDC + email whitelist). Adding an app is **one vhost**:

```
appname.{domain}  →  forward_auth (oauth2-proxy)  →  app's PWA backend  →  app /api
```

Every app inherits:

- a real HTTPS origin (which is what makes the service worker / PWA install legal
  at all — localhost won't cut it for real use),
- Google sign-in, once, for all apps (the SSO win),
- internal services that never publish a public port.

This is also the single biggest unlock for **scout specifically**: put it behind
this edge and it goes from "localhost, no auth, not installable" to "HTTPS,
authed, PWA-capable" without touching its Go code.

## Deployment — single VPS (decided)

The whole stack ships as **one docker-compose on a single small VPS** (~$7/mo
flat). This was weighed against Railway and a managed-DB hybrid; the VPS wins
because the platform's keystone — *one Caddy edge doing `forward_auth` + Google
SSO for every app over a private network* — is **already built** in
[`../compose/`](../compose/) and maps 1:1 to this host. Railway is excellent at
"deploy a service" but has **no built-in cross-service `forward_auth`**: getting
SSO in front of many apps there means running your own Caddy + oauth2-proxy as
services and proxying over `*.railway.internal` — i.e. rebuilding this compose on
Railway while losing the convenience that motivated it and taking on per-service
cost creep. Railway remains a fine choice for a *single-service spike* (brain +
Postgres + one app, weaker auth story, migrate later); it is not the choice for
the multi-app estate.

Honest tradeoff of the VPS: you own OS patching and Postgres backups. For a
single-user, low-traffic system that's a small, known cost — and self-hosted
Postgres in the compose stays free (no managed-DB dependency, no cross-host
latency). Revisit a managed DB (Neon/Supabase, both pgvector-capable) only if
backup/ops friction ever outweighs that simplicity.

Adding an app to the box is mechanical:

```
1. app gets a compose service on the internal network (no public port)
2. app gets one Caddy vhost:  appname.{domain} → forward_auth → app PWA → app /api
3. app's entry is added to the launcher registry (below)
```

The concrete contracts for steps 2 and 3 live in the appendix:

1. **Compose service** — internal-only, as above.
2. **Caddy vhost** — copy-paste the [vhost template](#appendix-copy-paste-contracts)
   and the [identity-header contract](#identity-the-x-auth-request-email-header) the
   app reads.
3. **Launcher registry entry** — add one entry per the
   [registry schema](#launcher-app-registry-schema).

## The launcher (the apps home)

You wanted "the brain shows what apps are connected and available to install."
That's the right product instinct — with one correction: it's an **app-layer
feature, fully portable across any host** (nothing about it needs a server vs
Railway). It is *not* a feature of the brain *service* — L1 stays a pure read API
(invariant 1 below). Its home is the **brainbot dashboard**, which is already your
owner dashboard: add an "apps home" view to it. ("The brain is the central app"
is right if it means the brainbot *dashboard*, not the brain *service*.)

The launcher is two small pieces:

- **An app registry** — curated config (a JSON list: `{name, icon, url,
  health}`), one entry per app. Hand-edited, matching the human-curated ethos;
  not ingested into the brain (system config isn't knowledge-about-you). The
  concrete schema (with `short_name` and a worked example) is in the
  [appendix](#launcher-app-registry-schema).
- **A launcher view** — renders a card per app, pings each app's `/healthz` to
  show *connected / offline*, and links out to each app's own URL.

The one hard PWA constraint to design around: **a launcher cannot install other
PWAs for the user.** `beforeinstallprompt` is per-origin, so each app is installed
from its own page. The real flow is: launcher card → "Open" → `appname.{domain}`
→ the user installs the PWA *there*. The launcher advertises and links; the
install happens at each app's origin.

## Migration path — scout is the first migrant

Scout is the proving ground because it's the app furthest from the contract. The
order matters (each step stands alone and is independently shippable):

1. **Extract the toolkit (L3).** Stand up `web-toolkit/` from brainbot's dashboard.
   Reconcile the two design systems into one set of tokens. This is the biggest
   single piece and gates everything after it.
2. **Rebuild brainbot's dashboard on the toolkit.** Lowest risk (it's the donor) and
   it validates the toolkit against a real app before scout depends on it.
3. **Pull scout's frontend out of `go:embed`.** The 3,920-line `index.html`
   becomes a toolkit-built PWA. Scout's Go server keeps serving its existing
   `/api/*` JSON unchanged — only the UI delivery changes. This is the heaviest
   scout-side lift; the `/api/*` surface already exists (it's listed in scout's
   `internal/web/server.go`), so it's a frontend re-home, not a backend rewrite.
4. **Put scout behind the edge (L2).** Add the Caddy vhost + a compose service.
   Scout inherits HTTPS + SSO + installability.
5. **App three is now cheap:** new backend (any language) + `npm create` from the
   toolkit + one vhost. That cheapness *is* the deliverable.

## Invariants (don't break these)

1. **The brain holds cross-app knowledge about you; apps hold their own working
   set.** No app writes the brain; no app duplicates another app's data. (Extends
   the existing scout invariant repo-wide.)
2. **Apps render no HTML from the backend.** Backend = `/api/*` JSON. UI = a
   toolkit PWA. (Retires scout's `go:embed` HTML model.)
3. **One design system, one shell, one service worker — from the toolkit.** An
   app must not hand-roll its own. Divergence here is the thing this whole doc
   exists to prevent. **No third-party component library:** the toolkit's
   components are scout's existing elements (buttons, cards, tables, modals,
   the SSE progress view) lifted as-is — the look is already good. Reach for a
   library only for a single genuinely-hard widget (virtualized grid, combobox,
   date picker), per-component, never as the foundation.
4. **Auth lives at the edge, never in the app.** Apps trust the identity
   oauth2-proxy injects; they contain no login code.
5. **Polyglot backends are fine; bespoke frontends are not.** The runtime is the
   app's choice; the frontend stack is the platform's.

## Open questions (decide when they bite)

- **Toolkit distribution.** Git-tag dependency to start (zero infra) vs a private
  npm registry once version churn hurts. Start with the former.
- **Per-app data stores.** *Resolved* — see [*App data: two kinds, and where the
  engines live*](#app-data-two-kinds-and-where-the-engines-live). Logical
  separation from the brain is non-negotiable; engine is per-app (SQLite for
  disposable/embedded like scout; a dedicated DB on the brain's Postgres server
  for durable/concurrent apps).
- **Capture (writing to the brain).** Still gated on a source-editing surface
  (see `architecture.md`). Until then, apps stay read-only consumers — which the
  contract already assumes.
- **Offline depth.** The toolkit's service worker should ship an offline *shell*
  first (cache assets, graceful "you're offline"); true offline *data* per app is
  app-specific and deferred until one actually needs it.
- **Change-aware reads.** How a caching consumer knows its cached brain view is
  stale *without a dumb TTL* — a cost cascade gated on the brain's `version`
  stamp, surfaced through a transport-agnostic `onChange` on L3's brain client.
  See the proposal in [`change-propagation.md`](./change-propagation.md); first
  consumer is scout's company-fit brief.

## How this relates to the other docs

- [`architecture.md`](./architecture.md) — the brain itself (L1) and the edge
  (L2). This doc builds L3 + L4 on top.
- [`consumer-integration.md`](./consumer-integration.md) / [`consumer-api.md`](./consumer-api.md)
  — the exact brain-read contract every app's brain client wraps.
- [`dashboard.md`](./dashboard.md) — the existing brainbot dashboard, i.e. the toolkit's donor.
- scout's `docs/north-star.md` — scout's own architecture; this doc governs how
  scout's *shell and delivery* align with siblings, not its pipeline.

## Appendix: copy-paste contracts

The prose recipe above (["Adding an app to the box is
mechanical"](#deployment--single-vps-decided)) and the
[launcher](#the-launcher-the-apps-home) describe what to do. This appendix is the
concrete, copy-paste version: the Caddy vhost, the identity header an app reads,
and the launcher registry schema. The launcher itself is story **US-004**.

### Caddy vhost template (a new app at the edge)

Modeled 1:1 on the existing dashboard host block in
[`../compose/Caddyfile`](../compose/Caddyfile) (the `brain.{$BRAIN_DOMAIN}`
block). Replace `appname` with your app's subdomain and `appname-pwa:8788` with
its internal service name and port. The app **publishes no public port** — only
Caddy talks to it over the docker network.

```caddyfile
# A new app: appname.{$BRAIN_DOMAIN}, Google-auth'd at the edge via oauth2-proxy.
# The app is unauthenticated inside the docker network and only ever sees
# requests oauth2-proxy has already cleared. No login code lives in the app.
appname.{$BRAIN_DOMAIN} {
    # oauth2-proxy's own routes (/oauth2/sign_in, /callback, /auth) get their
    # OWN handle block so they bypass forward_auth. Otherwise the sign-in page
    # is itself auth-gated, 401s, and the browser loops chaining rd=. handle
    # blocks are mutually exclusive, so /oauth2/* matches here and nowhere else.
    @oauth path /oauth2/*
    handle @oauth {
        reverse_proxy oauth2-proxy:4180
    }

    # Gate everything else on a valid, whitelisted Google session. On 401,
    # bounce the user into the sign-in flow and back to where they were.
    handle {
        forward_auth oauth2-proxy:4180 {
            uri /oauth2/auth
            copy_headers X-Auth-Request-Email X-Auth-Request-User

            @bad status 401
            handle_response @bad {
                redir * /oauth2/sign_in?rd={scheme}://{host}{uri}
            }
        }

        reverse_proxy appname-pwa:8788
    }
}
```

That's the entire edge integration. Authentication, HTTPS, and the email
whitelist are all inherited — the app adds nothing. Revocation stays "remove the
email from `compose/oauth2-proxy-emails.txt`," same as every other app.

### Identity: the `X-Auth-Request-Email` header

oauth2-proxy authenticates the user at the edge and `copy_headers` forwards the
identity into the request that reaches the app:

| Header | What it is |
|---|---|
| `X-Auth-Request-Email` | the signed-in user's email — the one an app reads |
| `X-Auth-Request-User` | the user id, also available |

The app **does not log anyone in** — auth lives at the edge (invariant 4). It
trusts these headers and surfaces the identity as a tiny read-only endpoint:

```
GET /api/me  →  { "email": "you@example.com" }
```

The app backend reads `X-Auth-Request-Email` off the incoming request and echoes
it as `/api/me`; the toolkit's `session` module
([`web-toolkit.md`](./web-toolkit.md)) consumes `/api/me` via `currentUser()`.
No tokens, no login UI, no per-app auth code.

### Launcher app-registry schema

The launcher (the brainbot dashboard's "apps home" view) renders one card per app from
a curated JSON array. This **extends** the `{name, icon, url, health}` shape
mentioned [earlier](#the-launcher-the-apps-home) by adding `short_name` (the
PWA-manifest short name, for the card label):

| Field | Type | What it is |
|---|---|---|
| `name` | string | full display name |
| `short_name` | string | compact label (matches the app's PWA `short_name`) |
| `icon` | string | URL/path to the app's icon |
| `url` | string | the app's origin — where the launcher card opens to |
| `health` | string | health-check URL the launcher pings (see below) |

One worked entry:

```json
[
  {
    "name": "brainbot",
    "short_name": "brain",
    "icon": "/icons/brainbot-192.png",
    "url": "https://brain.example.com",
    "health": "https://brain.example.com/healthz"
  }
]
```

This registry is **curated config, not ingested into the brain** — system config
isn't knowledge-about-you, so it never enters the brain's `sources`/`chunks`
(invariant 1). The launcher **health-pings each entry's `health` URL** and shows
the card as *connected* or *offline* accordingly, then links out to `url`.
Installing the app still happens at the app's own origin (`beforeinstallprompt`
is per-origin — see ["The launcher"](#the-launcher-the-apps-home)).
