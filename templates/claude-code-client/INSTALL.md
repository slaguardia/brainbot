# Wiring the brain into Claude Code

These steps install the Phase 1 client surface into a project repo where
you want Claude Code to read from the brain.

The "client repo" here is whatever repo you cd into and run `claude` from.
Nothing assumes a specific project layout or name.

## 0. Prerequisites

> **Heads up:** The brain stack uses a custom-built Graphiti image (not
> `zepai/knowledge-graph-mcp:latest`) and assumes Voyage with a payment
> method on file. If you haven't stood up the stack yet, skim the
> [README "Known limits"](../../README.md#known-limits--setup-gotchas)
> section first — there are a couple of setup footguns documented there
> that aren't obvious from the upstream Graphiti docs.

- Brain stack is up: FalkorDB + Graphiti + Caddy on your VPS.
- `BRAIN_DOMAIN` and `BRAIN_BEARER_TOKEN` are exported in your shell
  before launching `claude`. A reasonable spot is `~/.zshrc` or a
  wrapper script that sources `compose/.env` from your brainbot
  checkout.

**Privacy note:** the `UserPromptSubmit` hook installed in step 3
sends every prompt's first 2KB to your VPS (which then sends it to
your embeddings provider, Voyage by default) for vector search.
Set `BRAIN_INJECT_DISABLE=1` in a session to opt out for sensitive
prompts.

## 1. Add the brain MCP server

> **Note (Phase 2):** This used to point at the standalone Graphiti MCP
> server. That's been retired — the **brain service** now exposes its own
> MCP face at `/mcp` (tools: `recall`, `capture`) plus plain-HTTP routes.
> The API also moved host: it's now `brain.api.{domain}/mcp` (the bare
> `brain.{domain}` host is the human-facing PWA, Google-auth'd).

Current Claude Code expects MCP servers in `.mcp.json`, not
`settings.json`. Create `<client-repo>/.mcp.json`:

```json
{
  "mcpServers": {
    "brain": {
      "type": "http",
      "url": "https://brain.api.${BRAIN_DOMAIN}/mcp",
      "headers": {
        "Authorization": "Bearer ${BRAIN_BEARER_TOKEN}"
      }
    }
  }
}
```

The `${...}` placeholders are interpolated from your shell. Both env
vars must be set before launching `claude` from this repo.

### Local development variant

If you're running the brain stack on your laptop (the brain service is
exposed on `http://127.0.0.1:8100` with no Caddy auth via the local
overlay), use this `.mcp.json` instead:

```json
{
  "mcpServers": {
    "brain": {
      "type": "http",
      "url": "http://127.0.0.1:8100/mcp"
    }
  }
}
```

And export only `BRAIN_URL` (no bearer) before launching `claude`:

```sh
export BRAIN_URL=http://127.0.0.1:8100
unset BRAIN_BEARER_TOKEN
```

The hook honors `BRAIN_URL`/`BRAIN_BEARER_TOKEN` independently of
`.mcp.json`; with no token set, the `Authorization` header is omitted.

Verify in a fresh Claude Code session opened in the client repo:

```
list the available MCP tools
```

You should see `mcp__brain__recall` and `mcp__brain__capture`.

## 2. Document the env requirement in the client repo's CLAUDE.md

Append the following section to `<client-repo>/CLAUDE.md`:

```markdown
## Brain wiring

- The brain MCP server is configured in `.mcp.json` and gated behind
  a bearer token at `brain.{your-domain}`.
- Before launching `claude` from this repo, export both `BRAIN_DOMAIN`
  and `BRAIN_BEARER_TOKEN`. Without them set, the MCP server fails to
  authenticate and the brain tools will not appear in this session.
```

## 3. Install the memory injection hook (US-013)

Copy `inject_memory.py` from this directory into the client repo and
make it executable:

```sh
mkdir -p <client-repo>/.claude/hooks
mkdir -p <client-repo>/.claude/logs
cp inject_memory.py <client-repo>/.claude/hooks/inject_memory.py
chmod +x <client-repo>/.claude/hooks/inject_memory.py
```

Then add a `UserPromptSubmit` hook to
`<client-repo>/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/inject_memory.py",
            "timeout": 3
          }
        ]
      }
    ]
  }
}
```

The hook degrades silently on timeout or error (log lands at
`<client-repo>/.claude/logs/inject_memory.log`).

### Optional: scope the hook to a subset of repos

If you want the hook installed at the user level (`~/.claude/settings.json`)
but only active when you're working in specific repos, set
`BRAIN_INJECT_SCOPE` in your shell:

```sh
export BRAIN_INJECT_SCOPE=$HOME/code/with-brain
```

When set, the hook no-ops outside that path. When unset, it always
runs.

## 4. Smoke-test the hook

After steps 1–3, verify the hook actually reaches the brain and returns
hits. From inside the client repo:

```sh
BRAIN_URL=http://127.0.0.1:8100 \
  bash <path-to-brainbot>/templates/claude-code-client/smoke.sh "your test query"
```

It feeds a synthesized `UserPromptSubmit` payload to
`.claude/hooks/inject_memory.py`, prints the injected `<relevant-memory>`
block on success, and exits non-zero if the hook produced nothing (no
hits, timeout, or error — check `.claude/logs/inject_memory.log`).
