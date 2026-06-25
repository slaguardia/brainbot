# brainbot

**A private memory for you and the apps you build.**

You keep your notes in Notion. brainbot turns them into a small service that any app you build can ask questions about you — and get back *your own words*, never a guess.

The simplest way to picture it: a personal **librarian**. You write the books (your notes); it files them and finds the right page when something asks. It never rewrites your books, and it never makes up an answer — it just hands back what you actually wrote. It's built to be the shared foundation under many small personal apps, so each app stays tiny: the memory, the sign-in, and the look are all shared.

## The problem it solves

Most apps that "know things about you" keep their own private copy of who you are — your preferences in one app's settings, your history in another. Change your mind and you're editing five places, and no app knows what the others know.

brainbot flips that: **one place holds what's true about you, and every app reads from it.**

> **Example.** Keep your work history and the kind of job you'd actually take as ordinary Notion pages. Then build a tiny app that scores incoming job listings against them — without that app ever storing its own copy of "who you are." Edit the Notion page, and every app sees the change the next time it asks.

## The ideas that make it work

- **You write it; the machine just files it.** Your notes are the source of truth. brainbot never invents memories or silently "learns" things — it splits your pages into searchable pieces and keeps that index in step with whatever you wrote. Editing your memory just means editing the page.
- **It finds; your app decides.** Ask it something and you get back the relevant passages from your own notes — not a summary it dreamed up. What those passages *mean* is the app's job, not the memory's.
- **Two kinds of data, never mixed.** What's true about *you* lives in brainbot. An app's own scratch data — a job scorer's verdicts, a reading list's read/unread marks — lives with that app. Apps can *read* your knowledge; they can never scribble in it.
- **One front door for sign-in.** Everything sits behind a single gateway that handles Google sign-in. The apps themselves contain no login code at all.
- **It's yours, end to end.** The whole thing runs on one small server you own (about $7/month). The only thing it ever sends outside is the text it needs to turn into search data — and even that piece is swappable.

## How it works

```
You write a page in Notion
        │
        ▼
brainbot reads it, splits it into sections, and stores them
so they're searchable by meaning AND by exact keyword
        │
        ▼
Any app asks a question  ──►  gets back the closest passages, in your words
```

Under the hood it's a Postgres database with vector search (pgvector). Apps reach it over plain web requests, or — for AI tools like Claude Code — over MCP. No AI writes your memory anywhere in the pipeline; the only model involved is the one that turns text into searchable vectors.

## Why it's built this way

The design choices are the interesting part — here's the reasoning in plain terms.

**A plain database, not a "knowledge graph."**
I built the graph version *first* — the kind of database that stores facts as a web of connections between things. Then I noticed I never actually used the connections: every question was just "find the notes most related to this," which is search, not walking a web. So I switched to a regular database with strong search built in. Simpler, cheaper to run, and it does everything the graph did that I was actually using. *(The full story — what broke and what it taught me — is in [`docs/learnings.md`](./docs/learnings.md).)*

**A librarian, not an oracle.**
It hands back the relevant pages in your own words; it doesn't cook up an answer. Two reasons. First, many apps share it — if the memory decided what your notes "mean," every app would be stuck with that one interpretation, when a job scorer and a reading-list app need to read the same notes very differently. Second, the moment you let a model rewrite your notes into "facts," it quietly drops things — an earlier version of this lost my actual dealbreakers that way. Handing back your exact words means nothing gets lost in translation.

**Apps read; they never write.**
Your knowledge is the system of record, and a shared thing that five apps can scribble into becomes a junk drawer. So apps only ever read. Anything an app produces — verdicts, queues, scores — it keeps in its own storage. (Pulling a new Notion page *into* the memory is an owner action you do through the signed-in dashboard, not something an app can do.)

**Sign-in lives at the front door, not in the apps.**
One gateway handles Google sign-in for everything; the apps behind it just trust that you've been let in. That means one place to add or remove who's allowed, a tiny exposed surface, and — because the apps carry no login code — each app can be written in whatever language fits and they all get secure sign-in for free.

## How it compares

Products that "know things about you" split on two questions: **who writes the memory** — you, or an AI watching you — and **can your own code query it.** Every option trades something away; here's what each one costs *you*:

| | "Chat with your docs" (NotebookLM, …) | AI-memory APIs (Mem0, Zep, …) | brainbot |
|---|---|---|---|
| Who writes the memory | you upload, it summarizes | an AI extracts it from your chats | you write the pages |
| Can your apps query it | usually no | yes | yes |
| What you get back | a synthesized answer | extracted "facts" | your own passages |
| Where it lives | their cloud | their cloud | your server |
| **The catch for you** | your own apps can't tap into it | an AI writes it — and can quietly distort what you said | you write it down yourself |

The first two trade away **control**: either your apps can't reach the memory, or an AI decides what it says and keeps it on someone else's server. brainbot trades away **convenience** — nothing is remembered that you didn't write down. If you want a memory you *own*, that your *code* can use, that gives back *exactly what you wrote*, this is the only corner that gives you all three.

The full landscape — every neighbor and the honest trade-offs — is in [`docs/positioning.md`](./docs/positioning.md).

## Try it

Two containers — Postgres and the brain — on your laptop:

```sh
cd compose && cp .env.example .env      # set VOYAGE_API_KEY, NOTION_TOKEN, POSTGRES_PASSWORD
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
# pull in a Notion page, then search it:
curl -X POST http://127.0.0.1:8100/ingest -H 'Content-Type: application/json' \
  -d '{"url": "https://www.notion.so/Some-Page-<id>"}'
```

Full local walkthrough: [`docs/quickstart.md`](./docs/quickstart.md). Running it on a real server: [`docs/deployment.md`](./docs/deployment.md).

## Docs

The rest of the manual lives in [`docs/`](./docs) ([index](./docs/README.md)). Good starting points: [`architecture.md`](./docs/architecture.md) for how it's built, [`positioning.md`](./docs/positioning.md) for how it compares, and [`learnings.md`](./docs/learnings.md) for how the design got here.
