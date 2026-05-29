# A plain-English primer on RAG (and where brainbot fits)

A study guide for anyone (including future-you) trying to understand what RAG is, what GraphRAG adds, what all these tool names mean, and how this project relates to other note-taking tools you've used.

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

## 2. Naive RAG: the photocopied-snippets-in-a-box approach

The simplest, most common way to build RAG. This is what 90% of "I built an AI chatbot for our company docs" projects look like.

### How it works

1. Take every document you have (PDFs, web pages, notes).
2. **Chop them into snippets** — maybe one paragraph each.
3. For each snippet, ask an embedding model: "turn this paragraph into a list of 1500 numbers that represent its meaning." Those numbers are called a **vector** or **embedding**.
4. Throw all those vectors into a special database (a **vector database**) that can quickly answer: "given this query vector, which stored vectors are closest?"
5. When the user asks a question:
   - Embed the question the same way (question → vector).
   - Ask the vector database: "what are the 5 closest snippets?"
   - Take those 5 snippets, paste them into the prompt, send the whole thing to the LLM.

### Why "closest" works

Embeddings have a magical property: snippets about similar *meaning* end up with similar numbers, even if they don't share any words.

"My dog ate the homework" and "the puppy destroyed my essay" would land near each other in vector-space, even though zero words overlap. That's why this works for fuzzy questions.

### The "photocopies in a box" analogy

Think of it like this: you photocopy every page of every journal you own. You cut each photocopy into paragraph-sized snippets. You throw them all in a giant box, but you've magically labeled each snippet with a "vibe sticker" that says what it's about.

When someone asks a question, you read the question, generate the same kind of vibe sticker for it, and pull out the snippets with the most similar stickers. You hand those snippets to the consultant. They read and answer.

### Why this is great

- **Easy to build.** Three libraries and a weekend.
- **Works on any text.** PDFs, web pages, Slack messages — chop, embed, store.
- **Finds semantically similar stuff.** Doesn't need exact keyword matches.

### Why this isn't enough (the three failure modes)

**1. The system has no idea what's actually *in* the snippets.**

A snippet that mentions "Maya" and a different snippet that mentions "Maya Chen" are unrelated as far as the box knows. They might both come back for the same query, or only one might — there's no concept that they're the same person. Your "knowledge" is fragmented across snippets.

**2. Old wrong info stays in the box forever.**

You write in your journal "Maya works at Stripe." Later you write "Maya joined Acme." Both snippets are in the box. When you ask "where does Maya work?", whichever has the better vibe-match comes back — could be either. The system can't tell you the Stripe one is *outdated*.

**3. It can only follow one hop.**

If you ask "who do I know that's hiring backend devs?", the box finds snippets that talk about hiring backend devs. But if the snippet that mentions hiring doesn't *also* mention the person's name (because you wrote about the hiring in one journal entry and met that person in a different one), the box can't connect them. There's no concept of "follow the relationship from this person to their company to the company's job openings."

---

## 3. GraphRAG: the index-card system

GraphRAG fixes those three problems by storing things differently.

### How it works

Instead of a box of unrelated snippets, you build an **index card system**:

- Every distinct *thing* (a person, a company, a project, a concept) gets its own card.
- Cards have **strings tied between them** representing relationships: `Maya ── works at ── Acme`, `Acme ── is hiring for ── Rust developers`, `Maya ── previously at ── Stripe`.
- When someone asks a question, you find the most relevant starting card *and* follow the strings to gather everything connected.

### How the cards get made

You don't write them by hand. Every time you dump some text into the system, an LLM reads it and:
- Pulls out the things mentioned (creates or updates cards).
- Pulls out the relationships between them (ties or updates strings).
- Notices when new info contradicts old info and marks the old info "no longer true as of [date]" instead of deleting it.

This is what Graphiti does (see [how-it-works.md](./how-it-works.md) for the worked example with literal JSON).

### Why this fixes the three failure modes

**1. No more fragmentation.** Both "Maya" mentions become one card. Every fact about her attaches to that one card. Ask about Maya, get *everything* about Maya.

**2. No more stale info.** When you write "Maya joined Acme," the system sees the old "Maya works at Stripe" string and marks it "valid until June 7." Both strings still exist, so historical questions still work, but "where does Maya work now?" only returns the current one. This is the **bi-temporal** thing the other docs mention — every fact has a "true in the world" timeline.

**3. Multi-hop queries work.** "Who do I know that's hiring backend devs?" → find the "hiring backend devs" card → follow strings to "Acme" → follow strings to "Maya." The system stitches the chain together. The naive-RAG box can't do this.

### What you give up

- **Expensive writes.** Every time you dump text in, an LLM has to read it and decide what cards/strings to make or update. That costs money and takes a couple seconds. (Brainbot: ~$0.0016 per dump.)
- **Brittleness if extraction is wrong.** If the LLM mishears "Stripe" as "Stripey" you get a bad card and a wrong string. Naive RAG doesn't have this problem because it doesn't try to understand the text — it just stores it. Brainbot's hedge is the [human-edit surface](./human-edit-surface.md): you can fix bad cards yourself.

### Naive RAG vs GraphRAG, side by side

| | Naive RAG (box of snippets) | GraphRAG (index cards + strings) |
|---|---|---|
| What's stored | Chopped-up text + vectors | Things (cards) + relationships (strings) + vectors |
| What it knows about your data | Nothing — just "this snippet feels related to that one" | A lot — explicit identity ("this is Maya, the person") and explicit relationships |
| Handling duplicates | None — same person can appear in many snippets as if unrelated | Explicit dedup — one card per real-world thing |
| Handling outdated info | Stale snippets stay forever | Outdated facts get marked "no longer true as of date X" |
| Following chains | One hop only (snippet → answer) | Multi-hop — can walk relationships to connect things |
| Cost per write | Almost zero (just chop and embed) | Real money + seconds (LLM has to read and structure) |
| What can go wrong | Returns irrelevant snippets, misses fuzzy matches | LLM mis-extracts → wrong cards/strings (needs human edit) |
| Best for | "Answer questions about my docs" — broad coverage, fuzzy retrieval | "Reason about my world" — entities matter, time matters, chains matter |

Both are RAG. GraphRAG is just a more sophisticated flavor where the retrieval side knows more about your data's structure.

---

## 4. The tools zoo — what all those names actually are

The AI-tools landscape is a confusing zoo because vendors all describe themselves in jargon. Here's the plain-English version.

Think of building an AI app as cooking. Each tool is a different part of the kitchen.

### Vector databases — the spice rack

A vector database is just a storage system that's really good at one thing: storing lists of numbers (vectors/embeddings) and quickly finding "which stored lists are closest to this new list?"

That's it. It's specialized storage.

- **Pinecone** — the most well-known one. A hosted service: you pay them, they run the spice rack.
- **Weaviate, Qdrant, Chroma, Milvus** — competitors. Some self-hosted, some hosted.
- **pgvector** — a plugin that turns regular Postgres into a vector database, if you already use Postgres.

If your project is naive RAG, you almost certainly need one of these. If your project is GraphRAG, the graph database often has vector search built in (FalkorDB does), so you might not need a separate one.

### Graph databases — a different kind of pantry

A graph database is storage organized for things that are connected to other things. It's optimized for the "find this card, follow the strings" query pattern.

- **Neo4j** — the granddaddy. Industry standard. Mature, lots of tooling, well-known.
- **FalkorDB** — what brainbot uses. Newer, much more memory-efficient (fits on a tiny server). Speaks the same query language as Neo4j (Cypher).
- **ArangoDB, JanusGraph, Amazon Neptune** — other graph databases, less commonly used in personal-AI projects.

A graph database alone doesn't give you "AI." It's just storage. You still need something that reads text and writes cards/strings into it.

### Frameworks — the cookbook of pre-written recipes

When you build an AI app, you have to glue a bunch of services together: call the LLM, call the vector DB, format the prompt, parse the response, retry on errors. **Frameworks** are cookbooks of pre-written recipes for these glue tasks.

- **LangChain** — the most popular. Big Python and JavaScript libraries with helpers for "ask an LLM with context", "chain multiple LLM calls together", "build an agent", etc. Has a reputation for being overengineered, but it's everywhere.
- **LlamaIndex** — competitor to LangChain, more focused on the RAG use case specifically.
- **Haystack** — another option, more popular in enterprise NLP.

These frameworks are *not* the AI. They're the wiring that connects the AI services. Brainbot doesn't use any of them — the project is small enough to wire things together by hand, and avoiding the framework keeps the dependency footprint small.

### Graphiti — the personal chef who specializes in one recipe

Graphiti is a layer that sits on top of a graph database (FalkorDB or Neo4j) and does one specific thing really well: **take in raw text, use an LLM to extract entities and relationships, store them in the graph, handle dedup and bi-temporal updates, and expose search.**

It's not a framework — it doesn't try to help you build "any kind of AI app." It's one tool for one job: building a knowledge graph from messy text.

You could build everything Graphiti does yourself, but it'd take months. Graphiti is the value-add of "someone already figured out how to do this well." See [graph-engine.md](./graph-engine.md) for the full pitch.

### Putting it together: what brainbot is, in tool terms

- **FalkorDB** is the pantry (graph database with vectors built in).
- **Graphiti** is the chef who reads what you give them and organizes the pantry.
- **Anthropic Claude (Haiku)** is the LLM Graphiti uses to read and structure things.
- **Voyage** is the embedding service Graphiti uses to make the "vibe stickers" for vector search.
- **Caddy + Docker** are kitchen plumbing — hosting, networking, TLS.
- **The PWA and Claude Code hook** are the customers who walk up and order.

No LangChain, no Pinecone. Smaller stack on purpose.

---

## 5. How is this different from Obsidian or Notion?

Reasonable question. They all hold notes, right? Why isn't a knowledge graph just a fancy Obsidian?

### Obsidian

Obsidian is **a really nice paper notebook with two superpowers**: instant full-text search, and `[[wikilink]]` syntax that lets you make a link from one note to another.

It's built for **a human reading and writing**. The connections only exist if you (the human) explicitly wrote them. There's a graph view that shows your wikilinks as a pretty picture, but it's a *picture of links you typed*, not a system that understood your notes.

If your Obsidian vault has 500 notes and one of them mentions Maya without a wikilink, Obsidian has no idea Maya is a person. Full-text search will find the word "Maya" but won't connect it to anything.

### Notion

Notion is **a hybrid database + notebook + spreadsheet**. You can build structured tables ("People" database with columns for name, company, last contact) and link rows together. That gets you closer to a knowledge graph, but:

- *You* have to design the schema (define the columns, define what links to what).
- *You* have to fill in the structured fields manually.
- It's still optimized for humans reading and editing, not for an LLM querying.

### Graphiti + FalkorDB

This is **a notebook designed to be read by programs, not humans**. The differences:

| | Obsidian / Notion | Graphiti + FalkorDB |
|---|---|---|
| Who's the primary reader? | Human (you, scrolling and clicking) | Program (an LLM asking "what do you know about X?") |
| Who structures the data? | You, by hand (folders, tags, wikilinks, table columns) | An LLM, automatically, on every write |
| What happens when info changes? | You edit the page; old version may stay in version history | New fact contradicts old fact → old one marked outdated, both kept |
| Can you find "the founder of OpenClaw" if your note only says "Steve runs OpenClaw"? | Only if you wrote those exact words or made a wikilink | Yes — the system extracted "Steve" as a person and "runs" as a relationship |
| Can it answer "who do I know that's hiring Rust devs?" | Only via grep + you connecting the dots | Yes — multi-hop graph traversal |
| Is it pretty to look at? | Yes, that's a primary feature | Not really — the human-edit surface in brainbot is functional, not beautiful |

**The simplest way to think about it:** Obsidian is for *you*. Graphiti+FalkorDB is for *programs that act on your behalf*. They solve different problems. You could conceivably use both — Obsidian as your daily note-taking app, brainbot ingesting your notes nightly to make them queryable by your other apps.

The file-canonical alternative (markdown files as source of truth, graph as derived) that's mentioned in [human-edit-surface.md](./human-edit-surface.md) was actually trying to merge these two worlds. It got parked because the sync problem turned out to be harder than it looked.

---

## 6. Where brainbot fits in the broader landscape

Most "I built an AI thing" projects look like one of:

- **"Chatbot over our docs."** Naive RAG, vector store, off-the-shelf framework. Useful, common, doesn't differentiate.
- **"Agent that takes actions."** LLM + tool-calling + a loop. Trendy. Often demos well, often brittle in production.
- **"Personal AI assistant."** Some combination of the above two.

Brainbot is in a less-crowded slice: **personal GraphRAG, self-hosted, with the brain as the primary product and consumers as thin clients**. The pieces that make it distinctive:

- **GraphRAG, not naive RAG.** Most projects aren't doing this — vector-only RAG is the path of least resistance.
- **Self-hosted.** Most projects use hosted vector DBs and hosted LLMs. Brainbot owns the storage.
- **Bi-temporal facts.** Most RAG systems can't tell you when a fact stopped being true.
- **Brain-as-service.** Most projects build one app. Brainbot is built so many apps can share the same knowledge.

If you're using this for portfolio purposes, the angle is: "I built a personal GraphRAG system because vector-RAG fails on questions that need entity-resolution or temporal reasoning, and here's a defensible writeup of the tradeoffs at every layer."

That's a more interesting story than "I built a chatbot over PDFs."

---

## 7. If you want to go deeper

These are the things to read if you want to actually understand the field rather than just be able to talk about it.

**RAG fundamentals:**
- Anthropic's "Contextual Retrieval" blog post (improves naive RAG by adding document-level context to each chunk before embedding).
- The original RAG paper (Lewis et al, 2020) — short, readable, foundational.

**GraphRAG specifically:**
- Microsoft's GraphRAG paper (Edge et al, 2024) — the paper that put the name on the map.
- Neo4j's GraphRAG blog series — vendor-y but practical examples.

**The tools:**
- LangChain docs — even if you don't use it, knowing the vocabulary helps. Skim the "RAG" section.
- Graphiti's README on GitHub — the actual library you're using here.

**Embeddings:**
- OpenAI's embeddings guide — explains the "list of numbers represents meaning" intuition with examples.

Don't try to read everything. Pick one thing, work through it, then pick the next.

---

## TL;DR

- **RAG** = LLM gets a relevant cheat-sheet from your data before answering a question.
- **Naive RAG** = chop everything into snippets, find the most similar snippet, paste it in. Easy, ubiquitous, fails on identity / time / chains.
- **GraphRAG** = extract entities and relationships into a graph, query the graph. Harder to build, but handles identity / time / multi-hop questions.
- **Vector DBs (Pinecone)** = storage optimized for "find similar vectors."
- **Graph DBs (Neo4j, FalkorDB)** = storage optimized for "find connected things."
- **Frameworks (LangChain)** = pre-written glue code. Useful for fast prototyping, not used in brainbot.
- **Graphiti** = the layer that turns prose into a knowledge graph automatically.
- **Obsidian/Notion** = for humans to read and write. Brainbot = for programs to query on your behalf.
- **Brainbot** = self-hosted personal GraphRAG. Differentiated portfolio angle: most projects don't go past vector-only RAG.
