# Deployment runbook — VPS, the brain, and additional apps

End-to-end deploy of the full stack on a single VPS: provision the box, bring up
the brain core (Postgres + brain + dashboard), stand up the Caddy/SSO edge, then add
auxiliary apps (scout and beyond) one vhost at a time.

This is the concrete companion to the design docs: the *what* and *why* live in
[`architecture.md`](./architecture.md) (the brain + edge) and
[`app-platform.md`](./app-platform.md) (the app contract + the "adding an app is
mechanical" recipe). This doc is the *do-it-in-order* version.

The stack is fully expressed in `compose/docker-compose.yml` — `postgres`,
`brain`, `dashboard`, `scout`, `oauth2-proxy`, and `caddy` (the public edge). On the
VPS, `docker compose up -d --build` brings up everything; the local overlay
(`docker-compose.local.yml`) excludes the VPS-only services (`caddy`, `dashboard`,
`scout`).

---

## 0. Prerequisites (off the box)

Before touching the server, have these in hand:

- **A domain** you control DNS for. Everything lives under one apex, `${BRAIN_DOMAIN}`.
- **A Google OAuth client** (for dashboard/SSO). Google Cloud Console → APIs & Services
  → Credentials → *Create credentials* → *OAuth client ID* → *Web application*.
  - Authorized redirect URI: `https://brain.${BRAIN_DOMAIN}/oauth2/callback`
    (this one callback covers **every** app — the shared cookie domain means
    scout and future apps need no additional callback).
  - Keep the **Client ID** and **Client secret**.
- **A Voyage API key** with a payment method on file
  ([dashboard.voyageai.com](https://dashboard.voyageai.com/)) — the card just
  lifts the 3 RPM free-tier throttle that otherwise chokes ingest; tokens stay
  free at personal scale.
- **A Notion integration token** (for ingest) — or plan to set it later from the
  dashboard's `#integrations` page (DB-stored token overrides the env var).
- **An Anthropic API key** if you're deploying scout.

---

## 1. Provision the VPS

A ~$7/mo box is enough (1 vCPU / 1 GB RAM). Postgres alone is capped at `mem_limit: 1g`
in compose, so on a 1 GB box **add swap** (step 1.4) — the first brain image build
(`uv sync` pulls the Python dep tree) is the memory-hungry moment.

Use **Ubuntu 22.04 or 24.04 LTS**. The steps below assume a fresh root shell from
the provider; you'll create a non-root user and lock the box down.

### 1.1 Create a non-root sudo user + harden SSH

```sh
adduser deploy
usermod -aG sudo deploy
# copy your SSH key to the new user, then log back in as deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

**Disable password + root SSH login** — this is the single most important step,
and it's what makes the box secure with or without Tailscale. Confirm you can
log in as `deploy` with your key *first*, then:

```sh
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

With key-only auth, SSH brute force is mathematically a non-starter — keys aren't
guessable. fail2ban (step 1.5) is then log-noise reduction, not the thing
protecting you.

From here on, work as `deploy` and `sudo` when needed.

### 1.2 Install Docker Engine + Compose plugin

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
# log out and back in so the group takes effect, then verify:
docker compose version
```

### 1.3 Firewall (UFW) — only 80/443 public

The whole security posture is "Caddy is the only public door." UFW enforces it.

```sh
sudo apt-get update && sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH        # keep yourself out of a lockout
sudo ufw allow 80/443/tcp
sudo ufw enable
sudo ufw status verbose
```

> Do **not** publish the brain (8100) or Postgres (5432) to the host on the VPS.
> Those host-port mappings live only in `docker-compose.local.yml`, which is for
> laptops. On the VPS run plain `docker compose up -d` with **no** local overlay.

### 1.4 Swap (1 GB boxes)

```sh
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 1.5 fail2ban (SSH brute-force shield)

```sh
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
```

### 1.6 Tailscale for admin SSH (recommended)

Key-only SSH + UFW + fail2ban is already a secure baseline. Tailscale adds
defense-in-depth: it moves SSH onto a private tailnet so you can **close public
port 22 entirely**, leaving the box's only public ports as 80/443 — the strict
form of "Caddy is the only public door." It also removes the SSH login surface
from internet scans and any future OpenSSH 0-day. This is the recommended setup.

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Once you've confirmed you can SSH in over the tailnet, drop public 22:

```sh
sudo ufw delete allow OpenSSH
sudo ufw status verbose          # should now show only 80/443 from anywhere
```

> Skipping Tailscale is acceptable for a personal box **provided SSH is key-only**
> (step 1.1). Without that hardening, do not leave port 22 public.

---

## 2. DNS

Point the hostnames at the VPS public IP. Caddy gets TLS certs automatically from
Let's Encrypt, which needs these resolving **before** you bring the edge up.

| Record | Type | Value | Serves |
|---|---|---|---|
| `brain.${BRAIN_DOMAIN}` | A | VPS IP | dashboard (Google SSO) |
| `brain.api.${BRAIN_DOMAIN}` | A | VPS IP | brain API (bearer) |
| `scout.${BRAIN_DOMAIN}` | A | VPS IP | scout (if deploying it) |
| `<app>.${BRAIN_DOMAIN}` | A | VPS IP | one per future app |

A wildcard `*.${BRAIN_DOMAIN}` A record also works and means new apps need no DNS
change. Caddy still issues a separate cert per explicit vhost via the default
HTTP-01 challenge — the DNS-01 challenge is only needed for wildcard
*certificates*, which this setup doesn't use. Existing explicit records on the
domain (apex site, MX) take precedence over the wildcard and keep working.

---

## 3. Get the code + configure env

```sh
cd ~ && git clone <brainbot-repo-url> brainbot
cd brainbot/compose
cp .env.example .env
```

Edit `compose/.env` — the values that matter on the VPS (see `.env.example` for
the full annotated list):

```sh
BRAIN_DOMAIN=your-domain.com
BRAIN_BEARER_TOKEN=<openssl rand -hex 32>          # headless API auth
POSTGRES_PASSWORD=<a strong password>
VOYAGE_API_KEY=pa-...
NOTION_TOKEN=secret_...                             # or set later in the dashboard
GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-...
OAUTH2_PROXY_COOKIE_SECRET=<openssl rand -hex 16>      # raw 16/24/32-byte string; -hex 16 = 32 bytes. NOT -base64 32 (44 chars, rejected)
ANTHROPIC_API_KEY=sk-ant-...                        # scout only
```

Then the **email whitelist** for SSO — only these addresses can sign in to any
app at the edge:

```sh
cp oauth2-proxy-emails.txt.example oauth2-proxy-emails.txt
# one address per line
```

> **`.env` footguns** (both already mitigated by `env_file:` in compose, noted
> here so you don't reintroduce them): Compose only auto-loads `.env` from the
> compose dir, and `docker compose restart` does **not** reload `.env` — after
> editing it, do a full `down && up`, not `restart`.

---

## 4. The Caddy edge

Nothing to add here — the `caddy` service ships in `compose/docker-compose.yml`.
It's the public door and TLS terminator: it publishes 80/443 (the only host
ports on the box), sits on `brainnet` so it can reach each app by service name,
mounts `./Caddyfile`, and persists Let's Encrypt certs in the `caddy-data`
volume (kept across redeploys so you don't re-request certs — and risk Let's
Encrypt rate limits — on every `up`). It reads `{$BRAIN_DOMAIN}` /
`{$BRAIN_BEARER_TOKEN}` from `.env`.

The `Caddyfile` already defines the `brain.api`, `brain` (dashboard), and `scout`
vhosts. You don't edit it now — you'll add a vhost per new app in
[Step 7](#7-add-an-auxiliary-app-end-to-end).

---

## 5. Bring the stack up

From `compose/` (no local overlay on the VPS):

```sh
docker compose up -d --build
docker compose ps          # postgres + brain healthy; dashboard, oauth2-proxy, caddy up
docker compose logs -f caddy   # watch it obtain Let's Encrypt certs
```

The first build is multi-minute (the brain's `uv sync` pulls the Python dep
tree); later ups reuse the cached layer.

If deploying scout, its build context is the **sibling** `../../scout` repo (repos
are siblings on the box). Clone scout next to brainbot first, or scout's build
will fail — see [Step 7](#7-add-an-auxiliary-app-end-to-end).

---

## 6. Verify the brain

Run the live end-to-end smoke (ingest → recall/profile/map) against the public
API host:

```sh
cd ~/brainbot
BRAIN_URL=https://brain.api.${BRAIN_DOMAIN} \
BRAIN_BEARER_TOKEN=<your token> \
NOTION_TOKEN=<your token> \
python scripts/smoke_substrate.py
```

Then check the surfaces by hand:

- `https://brain.${BRAIN_DOMAIN}` → bounces through Google sign-in, then the dashboard
  (only whitelisted emails get in).
- `https://brain.api.${BRAIN_DOMAIN}/health` with `Authorization: Bearer <token>`
  → 200; without the header → 401.

First ingest (or do it from the dashboard's discover view):

```sh
curl -X POST https://brain.api.${BRAIN_DOMAIN}/ingest \
  -H "Authorization: Bearer <token>" \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.notion.so/Some-Page-<id>"}'
```

The page must be shared with the Notion integration, or you get a 4xx (Notion
404 = not shared). Re-ingesting wipes-and-replaces that page's chunks, so the
page stays the source of truth.

---

## 7. Add an auxiliary app (end-to-end)

Adding an app to the box is three mechanical pieces — a compose service, a Caddy
vhost, and a launcher entry. The contract (two-kinds-of-data rule, identity
header, what the backend must expose) is in
[`app-platform.md`](./app-platform.md); this is the deploy mechanics. scout is the
worked example baked into the repo.

**Ground rules for the service:**

- **No public port.** Only Caddy reaches it over `brainnet`. (scout listens on
  `:8765`, the dashboard on `:8787` — internal only.)
- **No login code.** Auth is at the edge; the app reads the
  `X-Auth-Request-Email` header oauth2-proxy injects and exposes it as `/api/me`.
- **Reads the brain at `http://brain:8100`** over `brainnet` — no bearer needed
  on-box. Working-set data lives in the app's own store (scout: SQLite on a
  volume), never in the brain's Postgres.

### 7.1 Compose service

Add the app next to `scout` in `docker-compose.yml`. Pattern (scout shown):

```yaml
  appname:
    build:
      context: ../../appname          # sibling repo on the box
      dockerfile: Dockerfile
    image: appname/appname:0.1
    container_name: appname
    restart: unless-stopped
    networks:
      - brainnet
    environment:
      # whatever the app's backend needs (e.g. ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY})
    volumes:
      - appname-data:/data            # only if it has a durable working set
    depends_on:
      brain:
        condition: service_healthy
```

Declare `appname-data:` under `volumes:` if you added one. Clone the app's repo
as a sibling of `brainbot/` first (`~/appname`), because the build context is
`../../appname`.

### 7.2 Caddy vhost

Append to `compose/Caddyfile` — identical to the scout block, swapping the
hostname and upstream `service:port`:

```caddyfile
appname.{$BRAIN_DOMAIN} {
    # /oauth2/* needs its OWN handle block so it bypasses forward_auth —
    # otherwise the sign-in page is itself auth-gated and the browser loops on
    # /oauth2/sign_in?rd=... (handle blocks are mutually exclusive, so this wins
    # for /oauth2/* and forward_auth never runs on it).
    @oauth path /oauth2/*
    handle @oauth {
        reverse_proxy oauth2-proxy:4180
    }

    handle {
        forward_auth oauth2-proxy:4180 {
            uri /oauth2/auth
            copy_headers X-Auth-Request-Email X-Auth-Request-User

            @bad status 401
            handle_response @bad {
                redir * /oauth2/sign_in?rd={scheme}://{host}{uri}
            }
        }

        reverse_proxy appname:<port>
    }
}
```

No new Google OAuth callback is needed — the shared `--cookie-domain
.${BRAIN_DOMAIN}` in oauth2-proxy means one sign-in covers every `*.${BRAIN_DOMAIN}`
host. Just add an A record for `appname.${BRAIN_DOMAIN}` ([Step 2](#2-dns)).

### 7.3 Launcher registry entry

Add the app to the dashboard's `#apps` launcher registry (a curated JSON list:
`{name, short_name, icon, url, health}`) so it shows up with a health ping. Schema
and a worked example are in
[`app-platform.md`](./app-platform.md#appendix-copy-paste-contracts).

### 7.4 Deploy the app

```sh
cd ~/brainbot/compose
docker compose up -d --build appname     # build + start just the new service
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile   # pick up the new vhost
```

Caddy fetches the cert for the new host on first request. Verify
`https://appname.${BRAIN_DOMAIN}` signs in and loads.

---

## 8. Day-2 operations

### Updates / redeploy

```sh
cd ~/brainbot && git pull
cd compose && docker compose up -d --build
```

For an app in a sibling repo: `git pull` that repo, then
`docker compose up -d --build appname`.

### Postgres backup (the one piece of real state)

The brain's chunks rebuild from re-ingest, but the **sources** and any
DB-stored config (e.g. the Notion token) live in Postgres. Back it up:

```sh
docker compose exec -T postgres pg_dump -U brain brain | gzip > brain-$(date +%F).sql.gz
```

Restore into a fresh stack:

```sh
gunzip -c brain-YYYY-MM-DD.sql.gz | docker compose exec -T postgres psql -U brain brain
```

Automate with a cron entry on the host; ship the dump off-box. You own backups —
that's the acknowledged VPS tradeoff (see
[`app-platform.md`](./app-platform.md#deployment--single-vps-decided)).

### Logs / health

```sh
docker compose ps
docker compose logs -f brain          # or dashboard / caddy / oauth2-proxy / scout
```

### Revoke a user

Remove their address from `compose/oauth2-proxy-emails.txt`, then
`docker compose restart oauth2-proxy`.

### Rotate the bearer token

Change `BRAIN_BEARER_TOKEN` in `.env`, `docker compose down && up -d` (a
`restart` won't reload `.env`), and update every headless consumer (Claude Code
clients, the migrator).
