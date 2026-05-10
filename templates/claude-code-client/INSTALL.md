# Wiring the brain into Claude Code

These steps install the Phase 1 client surface into a project repo where
you want Claude Code to read from the brain.

The "client repo" here is whatever repo you cd into and run `claude` from.
Nothing assumes a specific project layout or name.

## 0. Prerequisites

- Brain stack is up: FalkorDB + Graphiti + Caddy on your VPS.
- `BRAIN_DOMAIN` and `BRAIN_BEARER_TOKEN` are exported in your shell
  before launching `claude`. A reasonable spot is `~/.zshrc` or a
  wrapper script that sources `compose/.env` from your brainbot
  checkout.

## 1. Add the Graphiti MCP server (US-012)

Current Claude Code expects MCP servers in `.mcp.json`, not
`settings.json`. Create `<client-repo>/.mcp.json`:

```json
{
  "mcpServers": {
    "graphiti": {
      "type": "http",
      "url": "https://brain.${BRAIN_DOMAIN}/mcp",
      "headers": {
        "Authorization": "Bearer ${BRAIN_BEARER_TOKEN}"
      }
    }
  }
}
```

The `${...}` placeholders are interpolated from your shell. Both env
vars must be set before launching `claude` from this repo.

Verify in a fresh Claude Code session opened in the client repo:

```
list the available MCP tools
```

You should see `mcp__graphiti__search_nodes`, `mcp__graphiti__search_facts`,
and `mcp__graphiti__add_episode` in the response.

## 2. Document the env requirement in the client repo's CLAUDE.md

Append the following section to `<client-repo>/CLAUDE.md`:

```markdown
## Brain (Graphiti) wiring

- The Graphiti MCP server is configured in `.mcp.json` and gated behind
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
