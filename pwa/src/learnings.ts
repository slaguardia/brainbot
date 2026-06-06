// The "Evolution" content: an append-only story of how the brain's design
// evolved, chapter by chapter. Static, hand-authored content — it mirrors
// docs/learnings.md (keep them in sync). This module is just the
// content (section list + body HTML); the docs view (docs.ts) hosts it as a
// page in its sidenav and owns the chrome + scrollspy. innerHTML is safe — no
// user input. The chapter anchors stay `ch<n>` so old `#learnings/ch<n>` deep
// links keep resolving.

type Phase = { label: string; html: string };
type Chapter = {
  n: string;
  nav: string;
  title: string;
  status: "done" | "wip";
  phases: Phase[];
  principle: string;
  note?: string;
};

const CHAPTERS: Chapter[] = [
  {
    n: "0",
    nav: "0 · MCP server",
    title: "The off-the-shelf MCP server",
    status: "done",
    phases: [
      { label: "Believed", html: "Run the published Graphiti MCP server, point every client at it, done." },
      { label: "Broke", html: "The wrapper hid the controls a personal brain needs — extraction overrides, entity/edge types — and the image even shipped without its LLM providers." },
      { label: "Learned", html: "For a personal brain, <strong>the extraction layer <em>is</em> the product</strong>. A wrapper that hides it can't work." },
      { label: "Changed", html: "Dropped the standalone server; built our own service that imports <code>graphiti-core</code> directly and owns the whole pipeline." },
    ],
    principle: "Own the layer that is your value. Don't let a convenience wrapper own your extraction.",
  },
  {
    n: "1",
    nav: "1 · Atomic fan-out",
    title: "Atomic-fact fan-out",
    status: "done",
    phases: [
      { label: "Believed", html: "Cleaner input means better extraction — so split each capture into many tiny facts, one episode each." },
      { label: "Broke", html: "Rules <strong>shattered into instances</strong> (a location rule became a pile of city nodes), duplication everywhere, and it was painfully slow." },
      { label: "Learned", html: "Atomicity is not fidelity. A rule is a single thing; chopping it up destroys it." },
      { label: "Changed", html: "One faithful rewrite → <strong>one episode</strong>; let the tuned extractor pull the facts. No fan-out." },
    ],
    principle: "Preserve the shape of a thought. Rules stay whole; the extractor adapts to the thought, not the other way around.",
  },
  {
    n: "2",
    nav: "2 · Concepts",
    title: "Teaching the extractor to see concepts",
    status: "done",
    phases: [
      { label: "Believed", html: "With clean input, the stock extraction would do the job." },
      { label: "Broke", html: "Its prompt is built for Wikipedia-style names and <em>refuses abstract concepts</em> — it pulled ~2 entities and dropped everything that mattered." },
      { label: "Learned", html: "A personal brain wants <strong>salience, not notability</strong>: “would the owner want to remember this?”, not “could this have a Wikipedia article?”" },
      { label: "Changed", html: "Custom extraction instructions that push for concepts, values, and goals across any domain. Same input went <strong>2 → 20 entities</strong>." },
    ],
    principle: "A personal brain optimizes for salience, not notability. Tune the extractor to the owner's worldview.",
  },
  {
    n: "3",
    nav: "3 · Lossy patch",
    title: "The lossy-graph patch",
    status: "done",
    phases: [
      { label: "Believed", html: "Extraction's tuned now, so the graph holds everything — read the profile straight from it." },
      { label: "Broke", html: "The extractor keeps <em>positives</em> but drops <em>negatives and rules</em>: “avoids fintech” and “anything outside the set is a skip” lived in the captured text but never became facts." },
      { label: "Changed", html: "Patched the reads to return the raw captured <strong>text</strong> instead — restoring completeness, but quietly making the text the source of truth." },
      { label: "Learned", html: "That patch <strong>bypassed the database the brain exists to be</strong>. We'd treated a fixable tuning gap as a fundamental limit of graphs." },
    ],
    principle: "A workaround that bypasses your source of truth is a regression wearing a fix's clothes.",
  },
  {
    n: "4",
    nav: "4 · Source of truth",
    title: "Graph as the single source of truth",
    status: "done",
    phases: [
      { label: "Believe now", html: "Everything leaving the brain must come from the graph. Don't abandon it — make it faithful enough to trust." },
      { label: "Insight", html: "The losses were never “graphs can't”: negatives were an <em>instruction</em> gap, strength a missing <em>attribute</em>. Both fixable in-graph." },
      { label: "Changing", html: "Extract negatives; add one generic edge carrying <code>polarity</code> + <code>strength</code>; then read profile and recall from the graph and retire the text-dump." },
      { label: "Settled", html: "“Wall vs. weight” is just the <code>strength</code> value (the consumer decides what to do with it). No rule-nodes — the consuming LLM reasons over facts. And the first consumer (scout) must migrate off text-bodies <em>last</em>, only once the graph is faithful." },
    ],
    principle: "Most “fundamental limits” are untuned defaults — make the source of truth trustworthy instead of routing around it.",
    note: "Superseded — Path A (typed <code>polarity</code>/<code>strength</code> edges) shipped in Chapter 5, then the graph itself was reconsidered: the brain pivoted to a document substrate in Chapter 6.",
  },
  {
    n: "5",
    nav: "5 · Make the tags fire",
    title: "Making the tags actually fire",
    status: "done",
    phases: [
      { label: "Believed", html: "With Path A's typed edge and tuned descriptions in place, facts would come back carrying their <code>polarity</code>/<code>strength</code>. Ship it." },
      { label: "Broke", html: "Two silent failures only a live re-ingest exposed. <strong>Every tag came back <code>null</code></strong>: graphiti matches the extractor's relation label against the registered edge-type name by <em>exact</em> string, and its prompt mandates <code>SCREAMING_SNAKE_CASE</code> — we registered <code>Asserts</code>, the LLM emitted <code>ASSERTS</code>, so the attribute pass never ran. And a <strong>clearly-stated hard gate landed <code>soft</code></strong>: the firmness lived in a “skip everything else” clause — a set-complement with no entity for an entity→entity graph to anchor — so it dropped." },
      { label: "Learned", html: "A custom edge type is only as good as its <strong>name match</strong> — a flawless schema fails <em>silently</em> if the type name isn't what the extractor actually emits. And a “must be in set S” gate is captured by hard-positive facts <em>on S's members</em>, not by excluding the formless complement." },
      { label: "Changed", html: "Registered the type as <code>ASSERTS</code>; tuned the rewrite so a gated accept-set states its members as a hard requirement. The same source then landed location <code>hard</code> — requirement and skip both — with the broad soft/hard mix intact." },
    ],
    principle: "The model only tags what the substrate's matching rules and the graph's shape allow. Read the graph, not the code, to know what actually landed.",
  },
  {
    n: "6",
    nav: "6 · Document substrate",
    title: "The graph doesn't earn its keep",
    status: "wip",
    phases: [
      { label: "Believed", html: "A knowledge graph (FalkorDB via graphiti) was the right substrate — entities, typed edges carrying <code>polarity</code>/<code>strength</code>, bi-temporal facts. The premise: the value is <em>relationships</em>." },
      { label: "Broke", html: "<code>recall()</code> never uses the graph <em>as</em> a graph — it's hybrid semantic + BM25 (RRF) with <strong>zero multi-hop traversal</strong>, on a star topology where node-distance reranking was disabled because it can't help. The relationships benefit was never cashed in. The only real value was dedup + bi-temporal — and bi-temporal is two timestamp columns and a <code>WHERE</code> filter, not a graph feature. Meanwhile the graph <em>cost</em> us: no human-edit surface, a <code>polarity</code>/<code>strength</code> schema that coupled the brain to one consumer's gating, and a black box over the very RAG pipeline this project exists to learn." },
      { label: "Learned", html: "Pick the substrate by the <strong>read pattern</strong>, not by “is knowledge a graph.” Ours is semantic search → an LLM — a document/vector workload wearing a graph costume. And because the consumer is an LLM, <strong>structure belongs in the prose, not in columns</strong>: it reads “avoids fintech — hard dealbreaker” straight from the text. Over-decomposing into schema-tagged facts <em>caused</em> the wrinkles we kept fighting; storing the human's own sections fixes them for free." },
      { label: "Changed", html: "Pivoted to a <strong>document substrate</strong> — source-of-truth docs + derived section-chunks on pgvector. Editing a source wipes and re-derives its chunks, so currency is guaranteed by construction (no <code>invalid_at</code>). The brain is a reusable intelligence library with three reads — <code>recall</code>, <code>profile</code>, <code>map</code>; consumers are read-only; Notion nesting becomes a <code>path</code> for domain delineation." },
    ],
    principle: "A graph is a store you query by traversal — if you never traverse, you've paid for a graph and bought a document store. When the consumer is an LLM, keep the structure in the prose: the cleverness you remove is faithfulness you gain.",
    note: "The core migration has since landed — the brain now runs on the pgvector document substrate this guide's “How the brain works” describes. The next chapter gets written when this one breaks.",
  },
];

// The right-rail "on this page" entries for the Evolution page — one per chapter.
export const EVOLUTION_SECTIONS: { id: string; label: string }[] = CHAPTERS.map(
  (c) => ({ id: `ch${c.n}`, label: c.nav }),
);

function renderChapter(c: Chapter): string {
  const phases = c.phases
    .map((p) => `<div><dt>${p.label}</dt><dd>${p.html}</dd></div>`)
    .join("");
  const statusLabel = c.status === "wip" ? "in progress" : "settled";
  const note = c.note ? `<p class="tl-note">${c.note}</p>` : "";
  return `
    <li class="tl-item ${c.status === "wip" ? "current" : ""}" id="ch${c.n}">
      <div class="tl-marker"><span class="tl-num">${c.n}</span></div>
      <div class="tl-card">
        <div class="tl-head">
          <h2>${c.title}</h2>
          <span class="tl-status ${c.status}">${statusLabel}</span>
        </div>
        <dl class="tl-phases">${phases}</dl>
        <p class="tl-principle">${c.principle}</p>
        ${note}
      </div>
    </li>`;
}

// The Evolution page body — hero + the chapter timeline. The docs shell drops
// this into its content column and wires the right-rail scrollspy over the
// `.tl-item` chapters (anchors `ch<n>`).
export const EVOLUTION_BODY = `
  <header class="docs-hero">
    <h1>How the brain got smart</h1>
    <p class="docs-lead">
      The brain's value lives in its extraction and modeling layers — and those
      were <em>learned</em>, not designed up front. This is the story, chapter by
      chapter: what we believed, what broke, and what each break taught us.
    </p>
  </header>

  <ol class="timeline">
    ${CHAPTERS.map(renderChapter).join("")}
  </ol>`;
