# Human-edit surface

The PWA exposes a real **graph browser and editor** as a peer to chat and capture. Episodes, entities, and edges are directly viewable and editable. Edits hit Graphiti as mutations.

## Why this exists

Without it, "the graph is the source of truth" means "the human has no direct lever." With it, the human can fix bad extractions, rename entities, prune wrong edges, and merge duplicates. This is the strongest hedge against the bi-temporal-correction-only failure mode of graph-canonical systems — and the reason graph-canonical is viable at all ([memory-model.md](./memory-model.md)).

## What it covers

- **Entity card.** View, rename, merge with another entity, see all incident edges.
- **Episode editor.** View an episode, see what was extracted, re-extract if needed.
- **Edge inspector.** View, retire, or contradict a specific edge.
- **Search.** Free-text + filtered traversal.
- **Feed.** Infinite-scroll list of recent episodes.

Phase 2 builds these. Six initial mutations are scoped — real usage will reveal the seventh and eighth.

## The honest cost

Real product surface area. Entity card, episode editor, merge modal, search, feed — all need actual phone testing. It's a workstream of its own, not a side panel.

## Alternatives considered

- **Markdown-as-edit-format.** Render a node/episode as markdown, edit in a markdown pane, parse back into graph mutations on save. Rejected — the parser layer is a real cost and a direct graph UI is the simpler shape.
- **Read replica for speed.** Project the graph into a denormalized read store (SQLite or similar) for fast list views. Rejected as premature — no measured perf problem yet.
- **No editor, bi-temporal correction only.** Humans correct bad extractions by writing new contradictory episodes and trusting the bi-temporal store to invalidate the old fact. Rejected — relies entirely on the extractor doing the right thing and gives the human no direct lever.
- **File-canonical substrate (markdown + frontmatter as source of truth, graph as derived lens).** Parked. The most natural answer to the human-edit requirement, and it gives you "edit in Obsidian" for free, but the watcher's diff/conflict handling is a real engineering problem and bi-temporal correctness is harder when files are the write path. If the graph editor turns out to be too heavy, the partial revival is "let the human edit a markdown view of a single episode, parse changes back into mutations" without committing to files as the substrate.
