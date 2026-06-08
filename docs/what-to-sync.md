# What to sync to the brain

The brain is a reference library, not a backup. It splits every Notion page
into **one chunk per heading section** and retrieves those chunks by meaning.
So *what* you pull and *how those pages are written* decide how well the brain
recalls. A short rule of thumb: pull durable, well-structured knowledge you'd
want surfaced later — skip scratch, secrets, and giant unstructured dumps.

## Good to sync

- **Durable reference knowledge** — facts, decisions, profiles, notes you'd
  want recalled weeks from now.
- **Well-structured pages** — clear `H1`–`H3` headings, one topic per section.
  Headings carry the retrieval signal, so a page that's all headings and tight
  sections recalls far better than a wall of text.
- **Stable content** — the brain captures a page as a snapshot. Pages that
  don't change much stay accurate without constant re-pulls.

## Skip these

- **Scratch and transient notes** — stream-of-consciousness, meeting dumps,
  to-do lists. They have no heading structure, so each becomes one weak,
  catch-all chunk that pollutes recall.
- **Secrets and credentials** — anything you wouldn't want a downstream agent
  to read back. The brain returns raw facts to whatever consumer asks.
- **Big unstructured pages** — a page with no headings becomes a single giant
  chunk. Either add headings first or leave it out.
- **Duplicated content** — if the same fact lives on three pages, all three get
  found and split the recall. Keep one home per fact.
- **Highly volatile pages** — content that changes daily means a re-pull after
  every edit. Sync the parts that have settled.

## Make a page brain-ready first

Pages retrieve best when each section is self-describing: a real heading, one
topic, no facts duplicated from elsewhere. The **`curate-notion` skill**
(in Claude Code) does this automatically — it restructures Notion pages into
clean heading sections, dedupes facts across pages, and re-ingests the result.
Run it on a page (or a whole workspace) before pulling, and the brain gets
sharper source material to work with.

For the mechanics of how pages become chunks, see
[How the brain works](./brain-architecture.md).
