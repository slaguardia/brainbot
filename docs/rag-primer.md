# A plain-English primer on RAG (and where brainbot fits)

> Brainbot is **RAG on Postgres + pgvector**: sources split into embedded
> chunks, hybrid cosine + full-text recall fused with RRF. This primer explains
> that pattern from zero. (The project's first iteration was a knowledge graph;
> that era and why it ended live in [`learnings.md`](./learnings.md).)

A study guide for anyone (including future-you) trying to understand what RAG is, what the tool names mean, and how this project relates to other note-taking tools you've used.

No prior knowledge assumed. Lots of analogies. Skim the headings if you only need part of it.

---

## 1. The problem RAG solves

An LLM (like Claude or ChatGPT) is **a brilliant but amnesiac consultant**.

It's read most of the internet during training, so it knows general things — programming, history, how to write a polite email. But it knows nothing specific about *you*. It doesn't know your coworkers, your projects, what you decided last Tuesday, or that you've already tried option B and it didn't work.

You could just tell it everything every time you ask a question. That's exhausting, and there's a limit to how much you can fit in one message anyway.

**RAG (Retrieval-Augmented Generation)** is the pattern of: *before* the LLM answers your question, a separate system looks up relevant background info from your personal stash and quietly slips it into the conversation. Then the LLM answers with that context already in hand.

### The open-book exam analogy

Imagine you're taking an open-book exam. The test-taker is brilliant but only knows what's in their head plus what's on the desk.

- **Without RAG:** they only have what's in their head. They answer based on general knowledge.
- **With RAG:** there's a librarian. You ask a question, the librarian sprints to the stacks, grabs the three most relevant pages from your personal collection, and slides them across the desk *before* the test-taker has to answer. The test-taker reads those pages, then answers.

The librarian is the retrieval system. The pages are your data. The test-taker is the LLM. **R**etrieval-**A**ugmented **G**eneration = librarian-augmented test-taker.

### What "Retrieval-Augmented Generation" means, decoded

- **Retrieval** — go find the relevant stuff.
- **Augmented** — added on top of what the LLM already has.
- **Generation** — the LLM writing the answer.

That's the whole acronym.

---

## 2. How it works: snippets, vectors, and "closest wins"

This is what brainbot does on every recall.

1. Take every document you have (Notion pages, for brainbot).
2. **Chop them into snippets** — brainbot splits at headings, one chunk per section.
3. For each snippet, ask an embedding model: "turn this text into a list of numbers that represent its meaning." Those numbers are called a **vector** or **embedding**.
4. Store the vectors in a database that can quickly answer: "given this query vector, which stored vectors are closest?" (Postgres + pgvector, for brainbot.)
5. When a consumer asks a question:
   - Embed the question the same way (question → vector).
   - Ask the database for the closest snippets.
   - Hand those snippets to the consumer's LLM, which reasons over them.

### Why "closest" works

Embeddings have a magical property: snippets about similar *meaning* end up with similar numbers, even if they don't share any words.

"My dog ate the homework" and "the puppy destroyed my essay" would land near each other in vector-space, even though zero words overlap. That's why this works for fuzzy questions.

### The "photocopies in a box" analogy

You photocopy every page of every journal you own. You cut each photocopy into paragraph-sized snippets. You throw them all in a giant box, but you've magically labeled each snippet with a "vibe sticker" that says what it's about.

When someone asks a question, you generate the same kind of vibe sticker for the question and pull out the snippets with the most similar stickers. You hand those snippets to the consultant. They read and answer.

### The hybrid twist (what brainbot adds)

Pure vector search misses exact terms — a rare product name, an acronym, a number. So brainbot runs **two searches** on every recall: the vector search above *and* a classic full-text keyword search (`tsvector`). The two ranked lists are blended with **Reciprocal Rank Fusion (RRF)** — a simple formula that rewards items ranked high by either list, with no weights to tune. Semantic catches paraphrase; lexical catches exact tokens; the fusion stays robust when one arm is weak.

---

## 3. The classic RAG failure modes — and how brainbot handles them

Snippet-box RAG has three textbook weaknesses. Brainbot's answers come from its design (sources are human-edited and canonical; chunks are derived), not from extra machinery:

| Failure mode | The textbook problem | Brainbot's answer |
|---|---|---|
| **Fragmented identity** | "Maya" in one snippet and "Maya Chen" in another are unrelated as far as the box knows | Sources are **human-curated pages**, not random captures — one topic lives in one place, so facts about a thing sit together by construction. Residual near-duplicates are tolerated at read time; the consumer is an LLM. |
| **Stale facts linger** | You wrote "Maya works at Stripe," later "Maya joined Acme" — both snippets stay in the box forever | **Currency by construction**: editing the source page wipes and re-derives its chunks, so only current text is ever indexed. There's nothing stale to filter out. |
| **No multi-hop reasoning** | "Who do I know that's hiring backend devs?" needs facts connected across documents | The brain deliberately doesn't chain facts — it returns the relevant chunks and the **consumer's LLM connects the dots**. Keeping reasoning out of the brain is what lets one brain serve every app. |

---

## 4. The tools zoo — what all those names actually are

The AI-tools landscape is a confusing zoo because vendors all describe themselves in jargon. Here's the plain-English version.

Think of building an AI app as cooking. Each tool is a different part of the kitchen.

### Vector databases — the spice rack

A vector database is just a storage system that's really good at one thing: storing lists of numbers (vectors/embeddings) and quickly finding "which stored lists are closest to this new list?"

That's it. It's specialized storage.

- **Pinecone** — the most well-known one. A hosted service: you pay them, they run the spice rack.
- **Weaviate, Qdrant, Chroma, Milvus** — competitors. Some self-hosted, some hosted.
- **pgvector** — what brainbot uses: a plugin that turns regular Postgres into a vector database. One engine for relational rows, vectors, and full-text — no second database to operate.

### Frameworks — the cookbook of pre-written recipes

When you build an AI app, you have to glue a bunch of services together: call the LLM, call the vector DB, format the prompt, parse the response, retry on errors. **Frameworks** are cookbooks of pre-written recipes for these glue tasks.

- **LangChain** — the most popular. Big Python and JavaScript libraries with helpers for "ask an LLM with context", "chain multiple LLM calls together", "build an agent", etc. Has a reputation for being overengineered, but it's everywhere.
- **LlamaIndex** — competitor to LangChain, more focused on the RAG use case specifically.
- **Haystack** — another option, more popular in enterprise NLP.

These frameworks are *not* the AI. They're the wiring that connects the AI services. Brainbot doesn't use any of them — the project is small enough to wire things together by hand, and avoiding the framework keeps the dependency footprint small.

### Putting it together: what brainbot is, in tool terms

- **Postgres + pgvector** is the pantry (one engine: relational rows, vectors, and full-text).
- **The brain service** (`brain/`) is the chef — a small hand-written Python pipeline: split sources into section chunks, embed, store; retrieve with hybrid cosine + full-text fused by RRF.
- **Voyage** is the embedding service that makes the "vibe stickers" for vector search. There is **no write-time LLM** — ingest is split + embed + insert.
- **Caddy + Docker** are kitchen plumbing — hosting, networking, TLS.
- **The dashboard and Claude Code hook** are the customers who walk up and order.

No LangChain, no Pinecone. Smaller stack on purpose — the whole retrieval pipeline is owned code you can tune.

---

## 5. How is this different from Obsidian or Notion?

Reasonable question. They all hold notes, right?

### Obsidian

Obsidian is **a really nice paper notebook with two superpowers**: instant full-text search, and `[[wikilink]]` syntax that lets you make a link from one note to another.

It's built for **a human reading and writing**. The connections only exist if you (the human) explicitly wrote them. There's a graph view that shows your wikilinks as a pretty picture, but it's a *picture of links you typed*, not a system that understood your notes.

### Notion

Notion is **a hybrid database + notebook + spreadsheet**. You can build structured tables ("People" database with columns for name, company, last contact) and link rows together. But:

- *You* have to design the schema (define the columns, define what links to what).
- *You* have to fill in the structured fields manually.
- It's still optimized for humans reading and editing, not for an LLM querying.

### Brainbot

This is **a notebook designed to be read by programs, not humans**. The differences:

| | Obsidian / Notion | Brainbot |
|---|---|---|
| Who's the primary reader? | Human (you, scrolling and clicking) | Program (an LLM asking "what do you know about X?") |
| Who structures the data? | You, by hand (folders, tags, wikilinks, table columns) | You write normal pages with headings; the system splits, embeds, and indexes them automatically |
| What happens when info changes? | You edit the page; old version may stay in version history | You edit the source page; its chunks are wiped and re-derived, so only current text is ever indexed |
| Can you find "the founder of OpenClaw" if your note only says "Steve runs OpenClaw"? | Only if you wrote those exact words or made a wikilink | Usually — semantic search matches on meaning ("founder" ≈ "runs") |
| Is it pretty to look at? | Yes, that's a primary feature | Not the point — you edit your sources in Notion; the dashboard gives small read views |

**The simplest way to think about it:** Obsidian is for *you*. Brainbot is for *programs that act on your behalf*. They solve different problems. You could conceivably use both — Obsidian as your daily note-taking app, brainbot ingesting your notes nightly to make them queryable by your other apps.

In fact brainbot is built on exactly that split: **your human-edited pages (Notion today) are the source of truth**, and the machine index (chunks + vectors) is derived from them and rebuilt on every edit. Editing the brain = editing the page.

How brainbot relates to the rest of the landscape — NotebookLM, Supermemory and the Mem0-style agent-memory APIs, the Obsidian-as-AI-brain movement, assistants' built-in memory — is its own doc: [`positioning.md`](./positioning.md).

---

## 6. If you want to go deeper

**RAG fundamentals:**
- Anthropic's "Contextual Retrieval" blog post (improves plain RAG by adding document-level context to each chunk before embedding).
- The original RAG paper (Lewis et al, 2020) — short, readable, foundational.

**The tools:**
- pgvector's README on GitHub — the actual extension powering brainbot's vector search.
- LangChain docs — even if you don't use it, knowing the vocabulary helps. Skim the "RAG" section.

**Embeddings:**
- OpenAI's embeddings guide — explains the "list of numbers represents meaning" intuition with examples.

Don't try to read everything. Pick one thing, work through it, then pick the next.

---

## TL;DR

- **RAG** = LLM gets a relevant cheat-sheet from your data before answering a question.
- **How** = chop docs into chunks, embed them, find the closest chunks to the question, hand them to the LLM. Brainbot adds a keyword arm and fuses the two with RRF.
- **Vector DBs (pgvector)** = storage optimized for "find similar vectors." Brainbot's is built into Postgres.
- **Frameworks (LangChain)** = pre-written glue code. Useful for fast prototyping, not used in brainbot.
- **Obsidian/Notion** = for humans to read and write. Brainbot = for programs to query on your behalf — with your human-edited pages as the source of truth.
- **NotebookLM** = same grounded-in-your-sources bet, but a destination app with no API your code can query. **Supermemory** = same memory-API shape, but the memory is LLM-extracted automatically instead of human-curated.
- **Brainbot** = self-hosted personal RAG with the whole retrieval pipeline as owned, tunable code — and a human-curated memory your apps query over HTTP/MCP.
