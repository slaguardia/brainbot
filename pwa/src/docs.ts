// The documentation view — a knowledge base with a left sidenav. The sidenav
// carries the brain wordmark on top and a tab per PAGE ("How the brain works",
// "Evolution", and any future page); the center column holds the active page's
// article; the right rail is the in-page "on this page" tracker (scrollspy).
// Static, hand-authored content (no user input ever lands in this HTML, so
// innerHTML is safe). Reached via `#docs` (and `#docs/<page>`); `#learnings`
// (and `#learnings/ch<n>`) alias onto the Evolution page so old links resolve.
//
// The "How the brain works" content below describes the pgvector DOCUMENT
// SUBSTRATE — the brain is a Postgres + pgvector document store (sources →
// chunks → hybrid retrieval), not the old graphiti/FalkorDB graph. Keep it in
// sync with brain/ARCHITECTURE.md + brain/README.md (the authoritative sources).

import { EVOLUTION_BODY, EVOLUTION_SECTIONS } from "./learnings";

interface DocSection {
  id: string;
  label: string;
}
interface DocPage {
  id: string;
  label: string;
  sections: DocSection[];
  body: string;
}

const HOW_IT_WORKS_SECTIONS: DocSection[] = [
  { id: "overview", label: "Overview" },
  { id: "ingest", label: "Ingest pipeline" },
  { id: "recall", label: "Recall & profile" },
  { id: "store", label: "The document store" },
  { id: "endpoints", label: "Endpoints" },
  { id: "why", label: "Why this design" },
];

// Reusable bits ---------------------------------------------------------------

// Pipeline legend. The new substrate has NO generative LLM — the only model in
// the loop is the embedder, so there's no purple "LLM" chip.
const LEGEND = `
  <div class="legend" aria-hidden="true">
    <span class="chip c-vec">Embeddings · Voyage</span>
    <span class="chip c-search">Hybrid search</span>
    <span class="chip c-store">Postgres + pgvector</span>
    <span class="chip c-io">In / out</span>
  </div>`;

const HOW_IT_WORKS_BODY = `
      <header class="docs-hero">
        <h1>How the brain works</h1>
        <p class="docs-lead">
          A single self-hosted knowledge service that holds structured truth about
          one person — built as a <strong>Postgres + pgvector document store</strong>.
          Sources go in, get split into embedded chunks, and come back out by hybrid
          search. This page walks the write path, the read path, the store underneath,
          the endpoints, and why it's shaped this way.
        </p>
      </header>

      <!-- OVERVIEW ------------------------------------------------------------>
      <section class="docs-section" id="overview">
        <h2>Overview</h2>
        <p>
          The brain is domain-agnostic: it knows things <em>about you</em>, but
          nothing about what any app <em>does</em> with that knowledge. That's the
          whole trick — one brain can serve every app precisely because it never
          learns what a "job," a "calendar," or a "reading list" is.
        </p>

        <div class="note">
          <strong>One store, many thin consumers.</strong>
          The brain holds your sources and answers three reads — <code>recall</code>,
          <code>profile</code>, <code>map</code>. Everything else (this PWA,
          Claude&nbsp;Code in your terminal, any app you build) is a dumb client that
          calls in over HTTP or MCP. Cross-app knowledge lives in one place instead of
          being copied into each app.
        </div>

        <h3>A librarian, not an oracle</h3>
        <p>
          Ask the brain a question and it hands back the relevant passages it holds,
          each scored by how on-target it is. It never synthesizes, infers, or
          decides — that's the consumer's job. There's deliberately no <code>ask</code>
          endpoint; "asking the brain" <em>is</em> <code>recall</code>. The line in one
          sentence: <em>the brain hands back what it knows; the app reasons and
          decides.</em>
        </p>

        <div class="layers" role="img" aria-label="Three-layer model: app, brain, document store">
          <div class="layer k-app">
            <span class="layer-tag">App &nbsp;·&nbsp; scout, calendar prep, …</span>
            <strong>Task → scope / query → decision</strong>
            <p>Turns a task into the questions it needs answered, then reasons over the returned passages and decides: pursue / skip / maybe.</p>
          </div>
          <div class="layer-gap"><span>recall / profile&nbsp;↓</span><span>↑&nbsp;scored passages</span></div>
          <div class="layer k-brain">
            <span class="layer-tag">Brain &nbsp;·&nbsp; this service</span>
            <strong>Query → relevant passages</strong>
            <p>The librarian. No synthesis, no inference, no write-time LLM. Returns scored chunks with the source path behind each for tracing.</p>
          </div>
          <div class="layer-gap"><span>SQL · vector · FTS&nbsp;↓</span><span>↑&nbsp;rows</span></div>
          <div class="layer k-engine">
            <span class="layer-tag">Postgres + pgvector</span>
            <strong>sources · chunks · HNSW + tsvector indexes</strong>
            <p>The only persistent store. One asyncpg pool, opened on startup; the schema is applied idempotently on boot.</p>
          </div>
        </div>

        <div class="note">
          <strong>Sources are the truth; chunks are a disposable index.</strong> A
          <em>source</em> is a canonical document (a Notion page today). Its
          <em>chunks</em> are derived — split, embedded, and FK'd back to the source —
          and rebuilt from scratch on every ingest. That single rule, <em>currency by
          construction</em>, is what lets the rest of the design stay simple.
        </div>
      </section>

      <!-- INGEST --------------------------------------------------------------->
      <section class="docs-section" id="ingest">
        <h2>Ingest pipeline <span class="dir-badge dir-write">write path</span></h2>
        <p class="docs-lead">
          Free-text capture is retired. The write path is <strong>source ingest</strong>:
          point the brain at a document and it (re)derives that source's chunks. New
          capture, a human edit, and a re-sync are all the same call — and there's
          <strong>no generative LLM</strong> on this path. The only model it touches is
          the embedder.
        </p>

        ${LEGEND}

        <div class="flow" role="img" aria-label="Ingest pipeline flowchart">
          <div class="flow-node k-io">
            <span class="chip c-io">Input</span>
            <strong>POST /ingest { url }</strong>
            <p>A Notion page URL. Notion is the first migrator we ship; it's one of many possible source types.</p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-io">
            <span class="chip c-io">Fetch · Notion</span>
            <strong>1 · Fetch + flatten</strong>
            <p>
              Walk the page's block tree into markdown. Child pages stay as
              <code>[[refs]]</code> — they're separate sources, never inlined. The
              page's <code>path</code> is its Notion ancestry (parent titles joined by
              <code>/</code>, e.g. <code>Career/Job Search/Target Role</code>), and its
              real <code>last_edited_time</code> is kept as provenance.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-search">
            <span class="chip c-search">Chunk</span>
            <strong>2 · Split into chunks</strong>
            <p>
              <em>Phase 1: the whole page is one chunk</em> (position&nbsp;0, heading =
              the page title). The schema already carries <code>heading</code> and
              <code>position</code>, so heading-based section splitting is a drop-in
              next step.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-vec">
            <span class="chip c-vec">Embed · Voyage</span>
            <strong>3 · Embed</strong>
            <p>
              Each chunk is embedded with <code>voyage-3-lite</code> into a 512-dim
              vector (<code>input_type=document</code>). Embedding happens
              <em>before</em> the write, so an embedder failure aborts the ingest
              rather than leaving the source with stale or empty chunks.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-store">
            <span class="chip c-store">Postgres</span>
            <strong>4 · Upsert source + wipe-replace chunks</strong>
            <p>
              The <code>sources</code> row is upserted under the Notion page id (its
              stable source id). Then, in one transaction, that source's chunks are
              <code>DELETE</code>d and the fresh ones inserted. Re-posting the same URL
              is idempotent and always current.
            </p>
          </div>
        </div>

        <h3>The three things baked in here</h3>
        <ul class="reasons">
          <li><strong>Currency by construction.</strong> Because re-ingest wipes and replaces a source's chunks, <em>only current chunks ever exist</em>. There's no "valid until" timestamp to filter on and no write-time merge — the staleness problem is dissolved, not solved.</li>
          <li><strong>One source is the unit of truth.</strong> A new capture, a human edit in the editing surface, and a Notion re-sync are the same <code>upsert_source</code> call. Re-posting the same id never duplicates.</li>
          <li><strong>No write-time LLM.</strong> Ingest is fetch → split → embed → insert. The old pipeline ran two LLM passes (decompose + extract) on every capture; this one runs none. Meaning stays in the prose, where the consumer's LLM reads it.</li>
        </ul>

        <div class="note">
          <strong>Whole-page chunking is Phase 1.</strong> A very large page is
          truncated to an embed-input budget so ingest keeps working; real section
          splitting (and diff-and-re-embed instead of re-embedding the whole doc) is
          the planned next step. The source's faithful text is always stored intact —
          chunks are just the derived search index over it.
        </div>
      </section>

      <!-- RECALL --------------------------------------------------------------->
      <section class="docs-section" id="recall">
        <h2>Recall &amp; profile <span class="dir-badge dir-read">read path</span></h2>
        <p class="docs-lead">
          Reads are fast and use <strong>no generative LLM</strong> — just vector
          search, full-text search, and string assembly. The brain retrieves and
          scores; the reasoning happens in whatever consumer asked.
        </p>

        ${LEGEND}

        <div class="flow" role="img" aria-label="Recall pipeline flowchart">
          <div class="flow-node k-io">
            <span class="chip c-io">Input</span>
            <strong>Question (+ optional scope)</strong>
            <p><em>"what does the user want in a role?"</em> — sent verbatim as the query, optionally narrowed to a path subtree.</p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-search">
            <span class="chip c-search">Two arms · in parallel</span>
            <strong>1 · Semantic + lexical</strong>
            <p>
              A <strong>semantic</strong> arm (cosine distance over the pgvector HNSW
              index — the <code>&lt;=&gt;</code> operator, query embedded with
              <code>input_type=query</code>) and a <strong>lexical</strong> arm
              (<code>ts_rank</code> over a GIN <code>tsvector</code>) each pull ~50
              candidates. Running both means a thin or fragmented store still degrades
              gracefully.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-search">
            <span class="chip c-search">RRF · c=60</span>
            <strong>2 · Fuse</strong>
            <p>
              The two rankings are merged with Reciprocal Rank Fusion: each chunk
              scores <code>Σ 1/(60 + rank)</code> across the arms, and the top
              <code>k</code> survive. Both arms read one snapshot, so a wipe-replace
              committing mid-query can't fuse the same page in twice.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-io">
            <span class="chip c-io">Output</span>
            <strong>3 · Scored chunks → consumer decides</strong>
            <p>
              <code>{ heading, text, score, path }</code> per hit. The brain reports
              the fused score; it never thresholds. The consumer's own LLM filters,
              synthesizes, and decides.
            </p>
          </div>
        </div>

        <h3>Profile — the whole domain, assembled</h3>
        <p>
          Where <code>recall</code> finds the few best passages, <code>profile</code>
          takes a path <code>scope</code> and returns <em>every</em> chunk under it,
          ordered by <code>(path, position)</code> and reassembled into structured
          markdown — so a consumer that wants the complete record of a domain (not the
          answer to one question) gets it whole. If the bundle ever exceeds a token
          budget it degrades to recall-within-scope and says so (<code>truncated:
          true</code>) rather than silently cutting; at single-page scale it always
          fits.
        </p>

        <h3>Map — discovery</h3>
        <p>
          <code>map</code> returns the <code>(path, title)</code> tree of ingested
          sources, optionally under a scope — so a consumer that doesn't yet know its
          scope can find one. Scope everywhere means <em>the exact path node or its
          subtree</em>, never a bare prefix that would over-match siblings.
        </p>

        <div class="note">
          <strong>Scored, not thresholded.</strong> Recall attaches an on-target score
          and stops. The right cutoff is task-dependent — a gate question wants
          precision, a profile question wants completeness — and only the consumer
          knows the task. If everything scores low, the brain simply doesn't know.
        </div>
      </section>

      <!-- STORE ---------------------------------------------------------------->
      <section class="docs-section" id="store">
        <h2>The document store</h2>
        <p class="docs-lead">
          One engine holds everything: <strong>Postgres with the pgvector extension</strong>
          — relational rows, vector search, and full-text search in the same place. No
          graph database, no second store.
        </p>

        <h3>Two tables</h3>
        <div class="flow" role="img" aria-label="sources owns chunks">
          <div class="flow-node k-store">
            <span class="chip c-store">sources</span>
            <strong>The canonical document</strong>
            <p>
              <code>id</code>, <code>kind</code>, <code>title</code>,
              <code>raw_text</code>, <code>path</code>, <code>version</code>, plus two
              timestamps that mean different things: <code>source_last_edited</code>
              (the origin's real edit time) and <code>updated_at</code> (our last sync).
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>
          <div class="flow-node k-vec">
            <span class="chip c-vec">chunks</span>
            <strong>The derived, disposable index</strong>
            <p>
              <code>source_id</code> (FK, cascade), <code>heading</code>,
              <code>text</code>, <code>position</code>, <code>embedding vector(512)</code>,
              and a generated <code>fts tsvector</code>. Wiped and rebuilt whenever its
              source is re-ingested.
            </p>
          </div>
        </div>

        <h3>Two indexes do the retrieval</h3>
        <ul class="reasons">
          <li><strong>HNSW</strong> on <code>chunks.embedding</code> with <code>vector_cosine_ops</code> — the semantic arm. Approximate-nearest-neighbour over 512-dim Voyage vectors.</li>
          <li><strong>GIN</strong> on the generated <code>chunks.fts</code> tsvector — the lexical arm (<code>plainto_tsquery</code> / <code>ts_rank</code>).</li>
          <li>A <strong>btree</strong> on <code>sources.path</code> for fast scope (exact-node-or-subtree) matching.</li>
        </ul>

        <div class="note">
          <strong>The embedding is just an index.</strong> The source's text is the
          truth; the vector and the tsvector are derived columns rebuilt on every
          ingest. Lose them and you re-embed — you never lose knowledge. The schema is
          applied idempotently on boot, so a fresh database self-provisions.
        </div>
      </section>

      <!-- ENDPOINTS ------------------------------------------------------------>
      <section class="docs-section" id="endpoints">
        <h2>Endpoints</h2>
        <p class="docs-lead">
          Two front doors, one service: plain <strong>HTTP/JSON</strong> for typed
          consumers, and <strong>MCP</strong> (streamable HTTP at <code>/mcp</code>)
          exposing the reads as tools for Claude&nbsp;Code. Three reads — recall,
          profile, map — plus ingest and a health probe.
        </p>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method post">POST</span>
            <span class="path">/ingest</span>
            <span class="endpoint-tag">write</span>
          </div>
          <p>Fetch a Notion page, upsert it as a source, and re-derive its chunks (wipe-replace).</p>
          <pre><code>// request
{ "url": "https://www.notion.so/Target-Role-abc123…" }

// 200
{ "source_id": "abc123…", "chunks": 1, "path": "Career/Job Search/Target Role", "title": "Target Role" }</code></pre>
          <p class="endpoint-note">A missing/non-string <code>url</code>, a bad token, or a page the integration can't see comes back as a clear <code>400</code>; an unreachable Notion as <code>502</code>.</p>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/recall?q=&amp;scope=&amp;k=</span>
            <span class="endpoint-tag">read</span>
          </div>
          <p><code>q</code> required; <code>scope</code> optional (a path subtree); <code>k</code> defaults to 12 (clamped 1–100). Scored, not thresholded.</p>
          <pre><code>{
  "chunks": [
    { "heading": "Target Role",
      "text": "Wants a forward-deployed engineering role…",
      "score": 0.0312, "path": "Career/Job Search/Target Role" }
  ]
}</code></pre>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/profile?scope=&amp;budget=&amp;focus=</span>
            <span class="endpoint-tag">read</span>
          </div>
          <p>Every chunk under <code>scope</code>, assembled into markdown. <code>focus</code> only matters on the over-budget degrade path.</p>
          <pre><code>{
  "text": "# Career/Job Search\\n## Target Role\\n…",
  "sources": [
    { "path": "Career/Job Search/Target Role", "source_id": "abc123…",
      "title": "Target Role", "last_edited": "2026-05-31T18:04:00+00:00" }
  ],
  "truncated": false
}</code></pre>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/map?scope=</span>
            <span class="endpoint-tag">read</span>
          </div>
          <p>The <code>(path, title)</code> source tree, optionally under a scope. Discovery for a consumer that doesn't know its scope yet.</p>
          <pre><code>{ "sources": [ { "path": "Career/Job Search/Target Role", "title": "Target Role" } ] }</code></pre>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/health</span>
            <span class="endpoint-tag">liveness</span>
          </div>
          <p>Process-up only — it does <em>not</em> check the database. A cheap probe for healthchecks.</p>
          <pre><code>{ "ok": true }</code></pre>
        </div>

        <div class="note">
          <strong>MCP face.</strong> The same reads are exposed as tools
          <code>recall</code>, <code>profile</code>, and <code>map</code> at
          <code>/mcp</code> — one shared brain. <code>ingest</code> is HTTP-only. The
          legacy <code>POST /capture</code> is <strong>retired</strong>: this PWA
          answers it with <code>410 Gone</code>, and the brain has no such route. The
          PWA itself is read-only against the brain — it proxies only
          <code>/recall</code> and <code>/map</code>.
        </div>
      </section>

      <!-- WHY ------------------------------------------------------------------>
      <section class="docs-section" id="why">
        <h2>Why this design</h2>
        <p class="docs-lead">
          The brain used to be a knowledge graph (graphiti over FalkorDB). It isn't
          anymore. The short version of each decision:
        </p>

        <div class="decisions">
          <div class="decision">
            <h3>A document store, not a graph</h3>
            <p>Look at what recall actually did and the graph was never used <em>as</em> a graph — it was semantic + keyword search with zero multi-hop traversal, on a star topology where everything hung off the user. A document/vector workload wearing a graph costume. Pick the substrate by the read pattern: ours is semantic search → an LLM.</p>
          </div>
          <div class="decision">
            <h3>Postgres + pgvector, one store</h3>
            <p>Vectors, full-text, and relational rows in a single engine you already understand. No graph DB to operate, no second store to keep in sync. The only persistent store; logs go to stderr.</p>
          </div>
          <div class="decision">
            <h3>Currency by construction</h3>
            <p>A source owns its chunks; re-ingest wipes and replaces them. That dissolves the two things the graph was genuinely good at — bi-temporal invalidation and write-time dedup — into "only current rows exist." Bi-temporal was two timestamp columns and a filter, not a reason to keep a graph.</p>
          </div>
          <div class="decision">
            <h3>No write-time LLM</h3>
            <p>The old capture ran a decompose pass and an extraction pass on every note. The new ingest just splits and embeds. Cheaper, faster, and far less to go wrong — and the meaning isn't lost, it stays in the prose.</p>
          </div>
          <div class="decision">
            <h3>Structure in the prose, not columns</h3>
            <p>The consumer is an LLM, so typed fields like <code>polarity</code>/<code>strength</code> were the librarian doing the analyst's job. An LLM reads "avoids fintech — hard dealbreaker" straight from the text. Storing the human's own sections keeps negatives, gates, and nuance for free.</p>
          </div>
          <div class="decision">
            <h3>Hybrid retrieval with RRF</h3>
            <p>Semantic catches paraphrase; lexical catches exact terms and rare tokens. Reciprocal Rank Fusion blends them with no weight to tune, so the system stays robust when one arm is weak.</p>
          </div>
          <div class="decision">
            <h3>A librarian, not an oracle</h3>
            <p>The brain returns scored passages; it never synthesizes or decides. No <code>ask</code> endpoint. Keeping reasoning out is what lets one brain serve every consumer without learning any one domain.</p>
          </div>
          <div class="decision">
            <h3>RAG with the hood open</h3>
            <p>The graph was a black box over the very retrieval pipeline this project exists to learn. Now chunking, the embedder and its dimension, the HNSW index, the cosine query, the lexical arm, and the fusion are all owned and tunable — textbook RAG, in your hands.</p>
          </div>
          <div class="decision">
            <h3>Pluggable migrators</h3>
            <p>Notion is the first source we ship a migrator for, not <em>the</em> source — Obsidian, Roam, plain markdown are plausible siblings. The shared layer stays implicit until a second migrator earns it.</p>
          </div>
        </div>
      </section>`;

const PAGES: DocPage[] = [
  {
    id: "how-it-works",
    label: "How the brain works",
    sections: HOW_IT_WORKS_SECTIONS,
    body: HOW_IT_WORKS_BODY,
  },
  {
    id: "evolution",
    label: "Evolution",
    sections: EVOLUTION_SECTIONS,
    body: EVOLUTION_BODY,
  },
];

const DEFAULT_PAGE = "how-it-works";

function shellHTML(): string {
  const tabs = PAGES.map(
    (p) => `<a class="kb-tab" data-page="${p.id}" href="#docs/${p.id}">${p.label}</a>`,
  ).join("");
  return `
    <div class="kb">
      <aside class="kb-side">
        <a class="brand kb-logo" href="#" aria-label="brain — home">brain</a>
        <nav class="kb-tabs" aria-label="Documentation pages">${tabs}</nav>
      </aside>
      <main class="kb-content"><article class="docs-article"></article></main>
      <nav class="kb-toc" aria-label="On this page"></nav>
    </div>`;
}

// Which page the current hash selects. `#learnings*` aliases onto Evolution;
// `#docs/<page>` selects by id; anything else (including an old `#docs/<section>`
// deep link) falls back to the default page.
function pageFromHash(): string {
  const h = location.hash.replace(/^#/, "");
  if (h.startsWith("learnings")) return "evolution";
  const first = h.replace(/^docs\/?/, "").split("/")[0];
  return PAGES.some((p) => p.id === first) ? first : DEFAULT_PAGE;
}

// The section anchor a deep link points at, if any: `#docs/<page>/<section>` or
// `#learnings/<section>` (or the old `#docs/<section>`). "" when none.
function sectionFromHash(): string {
  const h = location.hash.replace(/^#/, "");
  if (h.startsWith("learnings")) return h.match(/^learnings\/(.+)$/)?.[1] ?? "";
  const parts = h.replace(/^docs\/?/, "").split("/");
  return PAGES.some((p) => p.id === parts[0]) ? parts[1] ?? "" : parts[0] ?? "";
}

let mounted = false;
let activePage = "";
let detachSpy: (() => void) | null = null;

export function mountDocs(container: HTMLElement): void {
  if (!mounted) {
    container.innerHTML = shellHTML();
    mounted = true;
    // Switch pages when the hash changes while we're in docs/learnings.
    window.addEventListener("hashchange", () => {
      if (/^#(docs|learnings)/.test(location.hash)) showPage(container, pageFromHash());
    });
  }
  showPage(container, pageFromHash());
}

function showPage(container: HTMLElement, pageId: string): void {
  const page = PAGES.find((p) => p.id === pageId) ?? PAGES[0];
  const switching = activePage !== page.id;
  activePage = page.id;

  container.querySelectorAll<HTMLAnchorElement>(".kb-tab").forEach((a) => {
    a.classList.toggle("active", a.dataset.page === page.id);
  });

  if (switching) {
    const article = container.querySelector<HTMLElement>(".kb-content .docs-article");
    if (article) article.innerHTML = page.body;
    const toc = container.querySelector<HTMLElement>(".kb-toc");
    if (toc) {
      toc.innerHTML =
        `<span class="kb-toc-title">On this page</span>` +
        page.sections
          .map(
            (s) =>
              `<a class="docs-nav-link" data-target="${s.id}" href="#docs/${page.id}/${s.id}">${s.label}</a>`,
          )
          .join("");
    }
    wireScrollspy(container, page);
    window.scrollTo(0, 0);
  }

  // Honor a section deep link on (re)entry.
  const sec = sectionFromHash();
  if (sec) document.getElementById(sec)?.scrollIntoView({ behavior: "auto", block: "start" });
}

// Right-rail scrollspy for the active page: smooth-scroll on click + highlight
// the section nearest the top of the viewport. Re-created on every page switch;
// the previous observer is disconnected first.
function wireScrollspy(container: HTMLElement, page: DocPage): void {
  detachSpy?.();
  const links = Array.from(
    container.querySelectorAll<HTMLAnchorElement>(".kb-toc .docs-nav-link"),
  );
  const byId = new Map(links.map((l) => [l.dataset.target ?? "", l]));
  const targets = page.sections
    .map((s) => document.getElementById(s.id))
    .filter((el): el is HTMLElement => el !== null);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  for (const link of links) {
    link.addEventListener("click", (e) => {
      const id = link.dataset.target ?? "";
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      history.replaceState(null, "", `#docs/${page.id}/${id}`);
    });
  }

  const setActive = (id: string) => {
    for (const l of links) l.classList.remove("active");
    byId.get(id)?.classList.add("active");
  };
  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((en) => en.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visible) setActive(visible.target.id);
    },
    { rootMargin: "-45% 0px -50% 0px", threshold: 0 },
  );
  for (const t of targets) observer.observe(t);
  setActive(targets[0]?.id ?? "");
  detachSpy = () => observer.disconnect();
}
