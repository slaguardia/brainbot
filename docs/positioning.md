# Where brainbot sits (and what makes it different)

Every product in the "AI that knows things about you" space answers the same
two questions, and the answers sort the whole landscape:

1. **Who writes the memory?** A human curates it · an LLM extracts it
   automatically · a recorder captures everything passively.
2. **Can your own code query it?** It's a destination app you visit · it's an
   API your apps call.

| | Destination app (you go to it) | API for your own apps |
|---|---|---|
| **Human-curated** | NotebookLM · Khoj, AnythingLLM, Reor ("chat with your docs") · Obsidian + AI plugins | **brainbot** — and almost nobody else (see below) |
| **LLM-extracted** | ChatGPT / Claude / Gemini built-in memory | Mem0 · Zep/Graphiti · Letta · LangMem · Supermemory — the crowded, funded "agent memory" category |
| **Passive capture** | Limitless-style recorders | Screenpipe and similar lifelog APIs |

## Brainbot's cell, stated precisely

Brainbot is the conjunction of five properties. Every neighbor shares some;
none shares all:

1. **A human writes the memory.** The brain's content is your edited pages
   (Notion today). No LLM ever authors, extracts, or "consolidates" what the
   brain believes.
2. **The machine derives the index.** Pages split at headings into chunks,
   embedded, stored — rebuilt from scratch on every edit, so the index can't
   drift from the page (*currency by construction*). The document is canonical;
   the index is disposable.
3. **It's a service, not a destination.** Any app queries it over HTTP or MCP —
   `recall` (search), `doc` (whole document by stable id), `map` (discovery).
   One brain, N consumers.
4. **Reads return faithful passages, not answers.** The brain is a librarian:
   it retrieves and assembles your own words; the *consumer's* LLM does the
   reasoning. There is no read-time synthesis and no write-time extraction —
   **the only model anywhere in the brain is the embedder.**
5. **Self-hosted, single-user.** Storage, pipeline, and API on your box.

The white space this lands in: a **human-curated memory served as an API that
returns source text**. The "chat with your docs" apps have human-curated
corpora but synthesize answers behind a chat UI; the agent-memory APIs are
queryable but let an LLM write the memory. The combination is the point.

## The neighbors, honestly

### Agent-memory APIs — Mem0, Zep/Graphiti, Letta, LangMem, Supermemory

The consensus "AI memory" category: a service your agents call, where a
**write-time LLM** turns conversations into memory — extracted facts (Mem0,
Supermemory), a temporal knowledge graph with edge invalidation (Zep/Graphiti),
or agent-managed memory tiers (Letta). Most are open-core with hosted products;
most speak MCP. Queries return extracted facts, graph edges, or assembled
profiles — interpretation included.

**Shared:** memory-as-a-service, API/MCP-first, hybrid retrieval (several even
sit on Postgres + pgvector).
**Different:** their memory is whatever extraction produced — it accumulates
automatically, can silently drop or distort what you said (extraction loses
negations and policies first), and editing what the system believes is rarely a
first-class surface. Brainbot's memory is exactly the page you wrote; editing
the brain is editing the page. The trade is honest: they give you memory
without effort; brainbot gives you memory without drift, and you do the
curating. (Brainbot ran the extraction design first and abandoned it for
exactly the drift problem — [`learnings.md`](./learnings.md).)

### Assistants' built-in memory — ChatGPT, Claude, Gemini

Each assistant auto-extracts a profile of you from your chats and injects it
into future conversations. Useful personalization — but it's the inverse of
brainbot on every axis: the LLM writes it, it lives in one vendor's app, no
third-party app can query it, and you can't self-host it. It personalizes
*their* product; it can't power *yours*.

### Grounded destination apps — NotebookLM; Khoj, AnythingLLM, Reor

These share brainbot's core belief: **your curated documents are the truth and
the AI must stay grounded in them.**

- **NotebookLM** (Google) is the polished end: upload sources, chat with
  citations, generate Audio Overviews. But it's a destination with **no public
  API to query a notebook from code** (the enterprise API manages notebooks;
  it can't ask them questions), it synthesizes answers, and it lives in
  Google's cloud. A notebook can never be the memory behind your own app.
- **Khoj / AnythingLLM / Reor** are the self-hosted end: bring your documents,
  get a semantic index and a chat UI. Khoj and AnythingLLM even expose APIs —
  but they're RAG endpoints that **synthesize an answer** with an LLM in the
  read path. None is positioned as brainbot is: faithful passages out, no
  model between the store and the consumer.

### The Obsidian-as-brain movement

The loudest current take on personal AI memory: keep your knowledge as a local
markdown vault ("file over app"), point Claude Code or an MCP bridge at the
folder, and the agent reads/writes your notes directly. The pitch is
zero-integration access — every agent already knows how to read files.

**This is brainbot's closest philosophical relative.** Same bet: human-edited,
human-readable documents as the canonical store; AI operates *on* them, never
*instead of* them. The interesting comparison is the **recall mechanism** — and
"the Obsidian approach" is really two very different ones:

- **Agent greps the vault** — the actually-hyped pattern ("file over app" +
  Claude Code / filesystem MCP). The agent runs `grep`/`glob` and reads whole
  files. As recall this is weak: **lexical only** (asking "where would I
  relocate?" won't find a note that says "open to SF or NYC" — no shared
  words), the **agent guesses what to read** (past a few hundred notes it can't
  read everything, and it burns context loading whole files to find one
  paragraph), and there's **no ranking** — you get matches, not relevance.
- **A vault + a real RAG plugin** (Smart Connections, Copilot, basic-memory) —
  embeds chunks and retrieves by similarity, which is *mechanically the same
  family* as brainbot's semantic arm. Honest call: against a well-built RAG
  plugin, brainbot's core recall is **comparable, not categorically better** —
  it's textbook hybrid RAG, not secret sauce.

| Recall property | Vault grep (the hyped one) | Vault RAG plugin | brainbot |
|---|---|---|---|
| Semantic (meaning) match | ✗ | ✓ | ✓ |
| Lexical (exact token) match | ✓ | sometimes | ✓ |
| Both, fused (RRF) | ✗ | rarely | ✓ |
| Section-level chunks, not whole files | ✗ | varies | ✓ |
| Ranked / scored results | ✗ | ✓ | ✓ |
| Index can't drift from source | n/a | ✗ (re-index on a schedule) | ✓ (rebuilt every edit) |

Where brainbot wins on *mechanism* (not setup friction): **hybrid fusion** —
semantic *and* lexical, fused with RRF, so a rare name/acronym/number and a
paraphrase both land, where most vault plugins do one or the other — and
**section chunking**, which returns the relevant passage instead of the whole
file dumped into context.

**But the categorical difference isn't quality — it's where recall lives, and
no amount of vault configuration fixes it.** In the vault world the recall
mechanism belongs to the **client**: the agent brings grep, this plugin brings
its embeddings, that plugin brings different ones — and whatever quality one
achieves is *trapped in that one tool's session*. Your other apps don't get it.
In brainbot, recall belongs to the **brain**: one maintained retrieval contract
— same hybrid search, same chunking, same ranking — that *every* consumer gets
identically over HTTP/MCP. The vault is bytes; the brain is bytes **plus a
guaranteed recall semantics** that travels to every app. That's the line that
survives any polish on the Obsidian side.

Two lesser differences round it out: vault access is **laptop-bound** (even the
MCP/REST bridges need Obsidian running on `127.0.0.1`), where brainbot is an
addressable server answering phone, terminal, and deployed apps concurrently;
and **editor choice** — the vault crowd edits markdown, brainbot's sources live
in Notion today, but the migrator contract is generic, so a markdown/Obsidian
migrator would simply make a vault one *source* feeding the served brain.

The tell: projects like basic-memory and Khoj's server mode are already
converging from the vault side toward exactly this — files as truth, derived
index, multi-client service — because the plugin-per-tool model doesn't get you
a shared recall contract. Brainbot simply starts there.

### Passive capture — lifelogging recorders

Record everything (screen, audio), transcribe, search the firehose. The
opposite curation bet: nobody writes the memory, so the memory is noise with
search on top. Useful as a *source* someday; not a competing design for a
curated brain.

## What this approach gives up

The differences above cut both ways. Choosing brainbot's cell costs:

- **You do the curating.** Nothing is remembered that you didn't write down.
  No effortless accumulation from chats — sessions don't remember themselves.
- **No polished destination UI.** The dashboard is a small owner console, not
  NotebookLM. The product is the API.
- **You run a server.** The "file over app" crowd avoids exactly this.
- **Single-user.** No sharing, no teams.

Those are accepted trades, not roadmap gaps: each one buys a property in the
list at the top.
