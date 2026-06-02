// The documentation view — a knowledge base with a left sidenav. The sidenav
// carries the brain wordmark on top and a tab per PAGE ("How the brain works",
// "Evolution", and any future page); the center column holds the active page's
// article; the right rail is the in-page "on this page" tracker (scrollspy).
// Static, hand-authored content (no user input ever lands in this HTML, so
// innerHTML is safe). Reached via `#docs` (and `#docs/<page>`); `#learnings`
// (and `#learnings/ch<n>`) alias onto the Evolution page so old links resolve.

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
  { id: "capture", label: "Capture pipeline" },
  { id: "recall", label: "Recall & profile" },
  { id: "endpoints", label: "Endpoints" },
  { id: "graph", label: "Graph database" },
  { id: "why", label: "Why this design" },
];

// Reusable bits ---------------------------------------------------------------

const LEGEND = `
  <div class="legend" aria-hidden="true">
    <span class="chip c-llm">Generative LLM</span>
    <span class="chip c-vec">Embeddings</span>
    <span class="chip c-search">Search</span>
    <span class="chip c-store">Graph store</span>
    <span class="chip c-io">In / out</span>
  </div>`;

const HOW_IT_WORKS_BODY = `
      <header class="docs-hero">
        <h1>How the brain works</h1>
        <p class="docs-lead">
          A single self-hosted knowledge service that holds structured truth about
          one person. This page walks the two LLM layers, the endpoints, the graph
          underneath, and why it's shaped the way it is.
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
          <strong>One smart brain, many thin consumers.</strong>
          All the intelligence — the capture pipeline, the recall scoring — lives
          in the brain. Everything else (this capture screen, Claude&nbsp;Code in
          your terminal, any app you build) is a dumb client that calls in over
          HTTP or MCP. Cross-app knowledge lives in one place instead of being
          copied into each app.
        </div>

        <h3>A librarian, not an oracle</h3>
        <p>
          Ask the brain a question and it hands back the relevant facts it holds,
          each scored by how on-target it is. It never synthesizes, infers, or
          decides — that's the consumer's job. It can never reason wrong, because
          it never reasons. The line in one sentence:
          <em>the brain hands back what it knows; the app reasons and decides.</em>
        </p>

        <div class="layers" role="img" aria-label="Three-layer model: app, brain, graph engine">
          <div class="layer k-app">
            <span class="layer-tag">App &nbsp;·&nbsp; scout, calendar prep, …</span>
            <strong>Task → questions → decision</strong>
            <p>Turns a task into the questions it needs answered, then reasons over the returned facts and decides: pursue / skip / maybe.</p>
          </div>
          <div class="layer-gap"><span>questions&nbsp;↓</span><span>↑&nbsp;relevant facts</span></div>
          <div class="layer k-brain">
            <span class="layer-tag">Brain &nbsp;·&nbsp; this service</span>
            <strong>Question → relevant facts</strong>
            <p>The librarian. No synthesis, no inference. Returns scored facts, with the faithful captures behind them available for tracing.</p>
          </div>
          <div class="layer-gap"><span>add_episode&nbsp;↓</span><span>↑&nbsp;search</span></div>
          <div class="layer k-engine">
            <span class="layer-tag">graphiti-core → FalkorDB</span>
            <strong>Extraction · dedup · bi-temporal facts · hybrid search</strong>
            <p>Constructed in-process by the brain. The graph engine and the only persistent store.</p>
          </div>
        </div>
      </section>

      <!-- CAPTURE -------------------------------------------------------------->
      <section class="docs-section" id="capture">
        <h2>Capture pipeline <span class="dir-badge dir-write">write path</span></h2>
        <p class="docs-lead">
          When you capture a thought it passes through <strong>two LLM layers</strong>
          before it lands in the graph. Capture is slow on purpose — both layers run
          before it returns — which is why this screen acknowledges optimistically and
          never makes you wait on it.
        </p>

        ${LEGEND}

        <div class="flow" role="img" aria-label="Capture pipeline flowchart">
          <div class="flow-node k-io">
            <span class="chip c-io">Input</span>
            <strong>Raw capture</strong>
            <p>Messy, first-person, as you'd type it: <em>"I only want forward-deployed roles with real customer contact — anything purely backend is a skip."</em></p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-llm">
            <span class="chip c-llm">LLM · Sonnet</span>
            <strong>1 · Decompose</strong>
            <p>
              Rewrites the raw text into faithful, named-subject prose the extractor
              can read well. "I/me/my" become your name. Rules stay rules — a hard
              gate stays one statement instead of shattering into a fact per excluded
              thing — and strength is preserved (a dealbreaker stays a dealbreaker).
              Invents nothing. Emits a short <code>topic</code> label plus a clean
              <code>body</code>.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-llm">
            <span class="chip c-llm">LLM · Haiku</span>
            <strong>2 · Extract</strong>
            <p>
              Inside graphiti. Reads the rewritten body and pulls out entities
              (Person, Organization, Topic, …) and the relationships between them,
              each as a natural-language fact. A custom instruction override tells it
              to capture values, goals, and preferences — graphiti's stock prompt
              refuses "abstract concepts," which for a personal brain is exactly
              backwards.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-vec">
            <span class="chip c-vec">Embed · Voyage</span>
            <strong>3 · Vectorize</strong>
            <p>Each entity and each fact is embedded into a vector so semantic search can find it later.</p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-store">
            <span class="chip c-store">graphiti</span>
            <strong>4 · Dedup + bi-temporal merge</strong>
            <p>
              Each entity is matched against existing nodes (one node per real-world
              thing). When a new fact contradicts an old one, the old fact is
              <em>superseded</em> — not overwritten — so history survives.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-store">
            <span class="chip c-store">FalkorDB</span>
            <strong>5 · Store</strong>
            <p>The entities, the facts, and the original episode body land in the graph.</p>
          </div>
        </div>

        <h3>The three design choices baked in here</h3>
        <ul class="reasons">
          <li><strong>Decompose before extract.</strong> graphiti's extractor works on named-subject, domain-explicit statements — not first-person preference prose. The rewrite reshapes the input into what it reads well, without losing rules or strength.</li>
          <li><strong>Override the extractor.</strong> The stock prompt says <em>"NEVER extract abstract concepts."</em> But your values and goals <em>are</em> the point of a personal brain. The override flips that — validated at 2&nbsp;→&nbsp;20 entities on the same input.</li>
          <li><strong>One episode, not many.</strong> An earlier design exploded each capture into one episode per atomic fact. It over-atomized (a single location rule shattered into a node per city), duplicated, and was slow. Now the tuned extractor gets one clean episode and pulls the facts itself.</li>
        </ul>

        <div class="note">
          <strong>The graph is the source of truth.</strong> The extracted facts —
          including negatives and gates, each carrying <code>polarity</code>
          (positive / negative) and <code>strength</code> (hard / soft) — are what
          consumers read. The rewritten episode body is kept alongside as the faithful
          capture: provenance you can trace back to, not the knowledge surface. Why
          that matters shows up in recall, next.
        </div>
      </section>

      <!-- RECALL --------------------------------------------------------------->
      <section class="docs-section" id="recall">
        <h2>Recall &amp; profile <span class="dir-badge dir-read">read path</span></h2>
        <p class="docs-lead">
          Reads are fast and — notably — use <strong>no generative LLM</strong>. The
          brain retrieves and scores; the actual reasoning happens in whatever
          consumer asked.
        </p>

        ${LEGEND}

        <div class="flow" role="img" aria-label="Recall pipeline flowchart">
          <div class="flow-node k-io">
            <span class="chip c-io">Input</span>
            <strong>Question</strong>
            <p><em>"what does the user want in a job?"</em> — sent verbatim as the query.</p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-search">
            <span class="chip c-search">Hybrid search · RRF</span>
            <strong>1 · Find candidates</strong>
            <p>
              graphiti runs a keyword search (BM25) and a vector search in parallel,
              then fuses the two rankings with reciprocal rank fusion. Running both
              means a fragmented graph still degrades gracefully instead of returning
              nothing.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-vec">
            <span class="chip c-vec">Embed + cosine · Voyage</span>
            <strong>2 · Score</strong>
            <p>
              The question is embedded; each candidate fact's stored embedding is
              fetched and the absolute cosine similarity is computed — an on-target
              <code>score</code> in roughly [0, 1]. The brain <em>reports</em> the
              score; it does not threshold. If every fact scores low, the brain
              simply doesn't know — no separate "I don't know" needed.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-store">
            <span class="chip c-store">Result</span>
            <strong>3 · Return scored facts</strong>
            <p>
              <code>facts</code> — precise and scored, each carrying
              <code>polarity</code> and <code>strength</code>. The extractor now
              captures negatives and gates as first-class facts, so "avoids&nbsp;X"
              and hard rules come back here too. The faithful episode bodies are
              returned only with <code>?debug=true</code> — provenance for tracing,
              not a knowledge surface.
            </p>
          </div>
          <div class="flow-arrow" aria-hidden="true"></div>

          <div class="flow-node k-io">
            <span class="chip c-io">Output</span>
            <strong>Consumer reasons &amp; decides</strong>
            <p>The brain stops at "here's what I know." The consumer's own LLM filters, synthesizes, and decides.</p>
          </div>
        </div>

        <h3>Profile — the whole picture, not one answer</h3>
        <p>
          <code>profile</code> is a flat list of every current fact — each with its
          <code>polarity</code> and <code>strength</code>. Use it when a consumer needs
          the complete record rather than the answer to a single question. At
          single-user scale the whole profile fits in a model's context, so handing
          back every fact sidesteps blind spots entirely.
        </p>

        <div class="note">
          <strong>Why the facts are enough.</strong> An earlier extractor pulled only
          positive facts and dropped negatives and rules — so an avoid-list or a hard
          gate survived only in the episode <em>body</em>, and recall had to hand back
          bodies to be complete. The extractor now captures those as first-class facts
          (with <code>polarity</code> and <code>strength</code>), so the graph carries
          the whole picture. Episodes are still stored as provenance and surface only
          under <code>?debug=true</code>. <em>Read the facts; the body is just the
          receipt.</em>
        </div>
      </section>

      <!-- ENDPOINTS ------------------------------------------------------------>
      <section class="docs-section" id="endpoints">
        <h2>Endpoints</h2>
        <p class="docs-lead">
          Two front doors, one service: plain <strong>HTTP/JSON</strong> for typed
          consumers, and <strong>MCP</strong> (streamable HTTP at <code>/mcp</code>)
          exposing the same operations as tools for Claude&nbsp;Code. Three
          operations — capture, recall, profile — plus a health probe.
        </p>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method post">POST</span>
            <span class="path">/capture</span>
            <span class="endpoint-tag">write</span>
          </div>
          <p>Runs the full decompose → extract pipeline, then returns. Seconds, not milliseconds.</p>
          <pre><code>// request
{ "text": "Talked to Beatrice from Globex; she's worried about Kafka cost." }

// 202
{ "mode": "rewrite", "episodes": 1, "topic": "Globex / Kafka cost concern" }</code></pre>
          <p class="endpoint-note"><code>400</code> if <code>text</code> is missing or blank. <code>mode</code> is <code>"raw"</code> when decomposition is disabled.</p>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/recall?q=&amp;limit=&amp;debug=</span>
            <span class="endpoint-tag">read</span>
          </div>
          <p><code>q</code> required; <code>limit</code> defaults to 20. Scored, not thresholded. Returns scored facts; pass <code>debug=true</code> to also get the episode bodies behind them.</p>
          <pre><code>{
  "query": "what does the user want in a job",
  "facts": [
    { "fact": "The user wants a forward-deployed engineering role.",
      "name": "WANTS", "score": 0.7421, "polarity": "positive", "strength": "soft",
      "valid_at": "2026-05-25T22:30:18+00:00", "invalid_at": null }
  ],
  "fact_count": 1
}
// with ?debug=true, an "episodes" array of faithful rewrites is included for tracing</code></pre>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/profile</span>
            <span class="endpoint-tag">read</span>
          </div>
          <p>Every current fact, each with its polarity and strength.</p>
          <pre><code>{
  "count": 1,
  "facts": [
    { "fact": "The user wants a forward-deployed engineering role.",
      "name": "WANTS", "polarity": "positive", "strength": "soft",
      "valid_at": "2026-05-25T22:30:18+00:00", "invalid_at": null }
  ]
}</code></pre>
        </div>

        <div class="endpoint">
          <div class="endpoint-head">
            <span class="method get">GET</span>
            <span class="path">/health</span>
            <span class="endpoint-tag">liveness</span>
          </div>
          <p>Process-up only. Brain construction is lazy, so this does <em>not</em> verify the database or the LLM — it's a cheap probe for healthchecks.</p>
          <pre><code>{ "ok": true }</code></pre>
        </div>

        <div class="note">
          <strong>MCP face.</strong> The same logic is exposed as tools
          <code>capture(text)</code>, <code>recall(query, limit=20)</code>, and
          <code>profile()</code> at <code>/mcp</code> — one shared brain instance.
          <code>health</code> is HTTP-only. The old standalone Graphiti MCP server's
          broad surface (<code>add_memory</code>, <code>search_nodes</code>,
          <code>clear_graph</code>, …) is deliberately <em>not</em> exposed — the
          contract is three operations.
        </div>
      </section>

      <!-- GRAPH ---------------------------------------------------------------->
      <section class="docs-section" id="graph">
        <h2>The graph database</h2>

        <h3>Episodes vs. facts</h3>
        <p>
          The brain holds two layers. An <strong>episode</strong> is one thing you
          captured — a passage of text, saved as-is: the faithful provenance record.
          A <strong>fact</strong> is a single structured claim the brain extracted
          from an episode ("X is CTO at Y"), stored as a connection in the graph and
          carrying its own polarity and strength. <strong>One episode produces many
          facts.</strong>
        </p>
        <p>
          The clearest picture is a <em>document and the structured record built from
          it</em>: the episode is the raw document, kept so any claim can be traced
          back; the facts are the graph the brain actually reads from — and because
          the extractor now captures "don'ts" and rules too, the facts carry the whole
          picture. Rule of thumb: <em>read the facts; reach for the episode only when
          you want to see where a fact came from.</em>
        </p>

        <h3>Nodes and edges</h3>
        <div class="graph-diagram">
          <svg viewBox="0 0 520 300" role="img" aria-label="Graph: owner hub with RELATES_TO facts, and an episode hub with MENTIONS edges">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#6c7484"></path>
              </marker>
            </defs>
            <!-- edges -->
            <g stroke="#2d3243" stroke-width="1.5" fill="none" marker-end="url(#arrow)">
              <line x1="250" y1="150" x2="95"  y2="70"></line>
              <line x1="250" y1="150" x2="95"  y2="230"></line>
              <line x1="250" y1="150" x2="420" y2="95"></line>
            </g>
            <g stroke="#403a5c" stroke-width="1.5" stroke-dasharray="4 4" fill="none" marker-end="url(#arrow)">
              <line x1="420" y1="215" x2="285" y2="170"></line>
              <line x1="420" y1="215" x2="430" y2="120"></line>
            </g>
            <!-- edge labels -->
            <text x="150" y="100" fill="#9099a8" font-size="11">RELATES_TO</text>
            <text x="150" y="205" fill="#9099a8" font-size="11">RELATES_TO</text>
            <text x="335" y="115" fill="#9099a8" font-size="11">RELATES_TO</text>
            <text x="318" y="205" fill="#a594ff" font-size="11">MENTIONS</text>
            <!-- owner hub -->
            <circle cx="250" cy="150" r="34" fill="#14171f" stroke="#8b6dff" stroke-width="2"></circle>
            <text x="250" y="154" text-anchor="middle" fill="#e8eaf0" font-size="13" font-weight="600">You</text>
            <!-- entity nodes -->
            <circle cx="78" cy="62" r="26" fill="#14171f" stroke="#7aa9ff" stroke-width="1.5"></circle>
            <text x="78" y="58" text-anchor="middle" fill="#c7d2e8" font-size="10">Topic</text>
            <text x="78" y="71" text-anchor="middle" fill="#8b94a6" font-size="9">forward-deployed</text>
            <circle cx="78" cy="238" r="26" fill="#14171f" stroke="#7aa9ff" stroke-width="1.5"></circle>
            <text x="78" y="234" text-anchor="middle" fill="#c7d2e8" font-size="10">Person</text>
            <text x="78" y="247" text-anchor="middle" fill="#8b94a6" font-size="9">Beatrice</text>
            <circle cx="445" cy="88" r="26" fill="#14171f" stroke="#7aa9ff" stroke-width="1.5"></circle>
            <text x="445" y="84" text-anchor="middle" fill="#c7d2e8" font-size="10">Org</text>
            <text x="445" y="97" text-anchor="middle" fill="#8b94a6" font-size="9">Globex</text>
            <!-- episode hub -->
            <rect x="402" y="196" width="86" height="40" rx="9" fill="rgba(139,109,255,0.08)" stroke="#8b6dff" stroke-width="1.5"></rect>
            <text x="445" y="214" text-anchor="middle" fill="#c2b8ff" font-size="10">Episodic</text>
            <text x="445" y="227" text-anchor="middle" fill="#9a90c0" font-size="9">a capture's body</text>
          </svg>
        </div>
        <p>
          Two node labels: <strong>Episodic</strong> (a capture's body) and
          <strong>Entity</strong> (an extracted thing, also tagged Person,
          Organization, Location, Event, Document, or Topic). Two edge types:
          <strong>RELATES_TO</strong> (entity → entity — the fact itself, carrying the
          sentence, its embedding, and timestamps) and <strong>MENTIONS</strong>
          (episode → entity — provenance: which capture a thing came from). There's no
          schema you define up front; the types are strings the extractor produces on
          the fly. Capture a sailboat tomorrow and you get a <code>Boat</code> entity
          with no code change.
        </p>

        <h3>Two hubs</h3>
        <p>
          Because everything is about one person, the graph naturally forms two
          well-connected hubs: the <strong>owner node</strong> (the web of what's true
          about you — the knowledge index) and each <strong>episode node</strong>
          (links to everything that capture produced — the source index, so any fact
          traces back to where it came from). Single-user by design, so the owner
          staying central is correct, not clutter.
        </p>

        <h3>Dedup</h3>
        <p>
          Before adding a <code>Maya</code> node, graphiti checks embeddings and name:
          is this the Maya we already have? If so, the new facts attach to the
          existing node instead of forking a duplicate. One node per real-world thing
          — the thing that's genuinely tedious to get right by hand.
        </p>

        <h3>Bi-temporal facts</h3>
        <p>
          Every fact carries <em>when it's true in the world</em>
          (<code>valid_at</code> / <code>invalid_at</code>) and <em>when the system
          learned it</em> (<code>created_at</code>). A correction doesn't overwrite —
          it supersedes. "Maya left Acme for a stealth startup" sets
          <code>invalid_at</code> on the old "Maya is CTO at Acme" fact and adds the
          new one. Both stay; <em>"where does Maya work now?"</em> returns only facts
          with <code>invalid_at = null</code>. In a plain vector store the stale
          sentence would keep surfacing forever — bi-temporal is what makes
          corrections actually stick.
        </p>

        <div class="note">
          <strong>FalkorDB underneath.</strong> The graph lives in FalkorDB — a Redis
          module that speaks Cypher, roughly 6× more memory-efficient than Neo4j (fits
          a small VPS), with vector indexes built in. graphiti supports Neo4j too, so
          switching is a config change, not a rewrite.
        </div>
      </section>

      <!-- WHY ------------------------------------------------------------------>
      <section class="docs-section" id="why">
        <h2>Why this design</h2>
        <p class="docs-lead">
          Every decision here is meant to be defensible. The short version of each:
        </p>

        <div class="decisions">
          <div class="decision">
            <h3>One smart brain, thin consumers</h3>
            <p>All the intelligence lives in the brain. Consumers stay dumb and narrow — this capture screen is just a proxy to <code>/capture</code>. Knowledge lives in one place instead of being copied into every app.</p>
          </div>
          <div class="decision">
            <h3>graphiti-core directly, not its MCP server</h3>
            <p>The standalone MCP server throws away the extraction override (the 2&nbsp;→&nbsp;20 entities hook), won't forward entity/edge type controls, and hardcodes a search recipe that bled domains. In-process, graphiti exposes every lever. The MCP server is kept only for Claude&nbsp;Code, where MCP is required.</p>
          </div>
          <div class="decision">
            <h3>Keep graphiti; don't go raw FalkorDB</h3>
            <p>Two things are genuinely hard to rebuild and are the real differentiators: entity <strong>dedup</strong> and <strong>bi-temporal</strong> fact invalidation. graphiti does both well, so we keep it rather than talking to FalkorDB directly.</p>
          </div>
          <div class="decision">
            <h3>The graph is the source of truth</h3>
            <p>Extraction now captures negatives and gates as first-class facts ("avoids X", "only Y counts"), each carrying polarity and strength. So the graph holds the whole picture — recall and profile return facts. Episodes are still stored as provenance and surface only under <code>debug</code>.</p>
          </div>
          <div class="decision">
            <h3>A librarian, not an oracle</h3>
            <p>The brain returns facts; it never synthesizes or decides. There's deliberately no <code>ask</code> endpoint — "asking the brain" is just <code>recall</code>. Keeping reasoning out is what lets it serve every consumer without learning any one domain.</p>
          </div>
          <div class="decision">
            <h3>Scored, not thresholded</h3>
            <p>Recall attaches an absolute on-target score to every fact and stops. The right cutoff is task-dependent — a gate question wants precision, a profile question wants recall — and only the consumer knows the task.</p>
          </div>
          <div class="decision">
            <h3>FalkorDB over Neo4j</h3>
            <p>Memory efficiency on a small VPS, Cypher-compatible, built-in vectors. Neo4j has deeper tooling; for a single-user brain the memory win wins. Swappable via config if that ever changes.</p>
          </div>
          <div class="decision">
            <h3>Retrieve broadly; don't over-tune ranking</h3>
            <p>At one-user / one-domain scale the whole relevant profile fits in a model's context. On a star topology every concept is ~2 hops from every other through the owner, so node-distance reranking doesn't help — recall uses RRF plus the fact text's own context. Ranking optimization is a scale problem we don't have yet.</p>
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
