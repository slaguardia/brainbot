# brainbot-pwa

Phase 2 surface: SvelteKit PWA + `@anthropic-ai/sdk` harness. Chat with your
brain, draft outreach, browse entities, watch `/admin` for cost.

**Status: scaffolded, not deployed.** Phase 1 (Graphiti + FalkorDB online) is
the prerequisite. UI shell runs standalone; tools and graph viz return
"phase-1-not-online" until the backend is up.

Verified locally on 2026-05-13:
- `npm install` → 124 packages, 0 warnings.
- `npm run check` → 0 errors, 0 warnings.
- `npm run build` → succeeds, output size reasonable (renderer ~94kB).
- `node build` → boots; `/`, `/admin`, `/explore`, `/entity`, `/draft`,
  `/api/health`, `/manifest.webmanifest` all return 200.
- `/api/health` correctly reports `anthropic: false, postgres: false, …`
  when env is empty.

See `../plans/phase-2-decisions.md` for design rationale and what's
intentionally stubbed.

## Layout

```
pwa/
├── src/
│   ├── app.css                    design tokens (D7)
│   ├── app.html
│   ├── service-worker.ts          offline shell, no API caching
│   ├── lib/
│   │   ├── components/            Composer, MessageBubble, ToolCallCard, NavRail, EntityCard
│   │   ├── server/
│   │   │   ├── anthropic.ts       SDK client
│   │   │   ├── db.ts              pg pool
│   │   │   ├── env.ts             env access with graceful fallbacks
│   │   │   ├── falkor.ts          FalkorDB direct (graph viz subgraphs)
│   │   │   ├── graphiti.ts        REST client; phase-1-blocked
│   │   │   ├── pricing.ts         model → $ per Mtok
│   │   │   ├── system-prompt.ts
│   │   │   ├── admin.ts           /admin metric queries
│   │   │   └── tools/             tool definitions + instrument wrapper
│   │   └── types.ts
│   └── routes/
│       ├── +layout.svelte         shell with NavRail
│       ├── +page.svelte           /  → chat (D5: chat-first)
│       ├── entity/
│       │   ├── +page.svelte       /entity  → index (phase-1-blocked)
│       │   └── [id]/+page.{svelte,server.ts}
│       ├── explore/+page.svelte   /explore → force-directed viz placeholder (D2)
│       ├── draft/+page.svelte     /draft   → focused workflow
│       ├── admin/+page.{svelte,server.ts}  /admin → cost + tool calls
│       └── api/
│           ├── chat/+server.ts            SSE streaming + tool-use loop
│           ├── transcribe/+server.ts      Tier-2 voice → Groq Whisper
│           ├── graph/neighborhood/+server.ts
│           └── health/+server.ts
├── migrations/                    SQL files; runner in scripts/migrate.mjs
├── deploy/
│   ├── docker-compose.pwa.yml     additive — merge into main compose
│   └── Caddyfile.snippet          additive — merge into main Caddyfile
├── Dockerfile
└── package.json
```

## Local dev

```bash
cd pwa
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY and DATABASE_URL.

npm install
npm run migrate            # applies migrations/*.sql to DATABASE_URL
npm run dev                # → http://localhost:5173
```

The UI loads even with no env set; you'll see streaming chat errors until
`ANTHROPIC_API_KEY` is set, and tool calls fall back to "phase 1 not online"
responses until `GRAPHITI_URL` is reachable.

## Voice input

Tier 0 ships with phase 2 — the composer is a real `<textarea>`, so iOS keyboard
dictation works automatically. No mic button.

Tier 2 (Groq Whisper hold-to-talk) is wired at `/api/transcribe`. Set
`GROQ_API_KEY` and add the mic button to `Composer.svelte` when you're ready.
See `../plans/phase-2-decisions.md` §D6.

## Things explicitly NOT in this scaffold

- Live deployment (phase 1 / 1.5 prerequisites)
- Force-directed graph viz library + page (defer until graph has data)
- Voice Tier 2 mic button in the composer (Groq Whisper endpoint exists at
  `/api/transcribe`; UI wiring deferred to phase 2.x)
- Tests (add when phase 2 lands)
