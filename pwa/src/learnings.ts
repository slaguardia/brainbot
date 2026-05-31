// The learnings timeline view: an append-only story of how the brain's design
// evolved, chapter by chapter. Static, hand-authored content — it mirrors
// LEARNINGS.md at the repo root (keep them in sync). A separate page from the
// docs view, but shares its chrome (topbar + nav rail + article) and is reached
// from the docs topbar's "Evolution" link. Routed at `#learnings` (and
// `#learnings/ch<n>` deep links) by main.ts. innerHTML is safe — no user input.

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
    status: "wip",
    phases: [
      { label: "Believe now", html: "Everything leaving the brain must come from the graph. Don't abandon it — make it faithful enough to trust." },
      { label: "Insight", html: "The losses were never “graphs can't”: negatives were an <em>instruction</em> gap, strength a missing <em>attribute</em>. Both fixable in-graph." },
      { label: "Changing", html: "Extract negatives; add one generic edge carrying <code>polarity</code> + <code>strength</code>; then read profile and recall from the graph and retire the text-dump." },
      { label: "Settled", html: "“Wall vs. weight” is just the <code>strength</code> value (the consumer decides what to do with it). No rule-nodes — the consuming LLM reasons over facts. And the first consumer (scout) must migrate off text-bodies <em>last</em>, only once the graph is faithful." },
    ],
    principle: "Most “fundamental limits” are untuned defaults — make the source of truth trustworthy instead of routing around it.",
    note: "In progress — see plans/graph-as-source-of-truth.md. The next chapter gets written when this one breaks.",
  },
];

const NAV = CHAPTERS.map(
  (c) => `<a class="docs-nav-link" data-target="ch${c.n}" href="#learnings/ch${c.n}">${c.nav}</a>`,
).join("");

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

const LEARNINGS_HTML = `
  <div class="docs-topbar">
    <a class="docs-back" href="#" aria-label="Back to capture">
      <span class="docs-back-arrow" aria-hidden="true">←</span> Capture
    </a>
    <span class="brand" aria-label="brain">brain</span>
    <a class="docs-cross" href="#docs" aria-label="How the brain works">Docs&nbsp;→</a>
  </div>

  <div class="docs-body">
    <nav class="docs-nav" aria-label="Timeline chapters">${NAV}</nav>

    <article class="docs-article">
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
      </ol>

      <footer class="docs-foot">
        <a class="docs-back" href="#docs"><span class="docs-back-arrow" aria-hidden="true">←</span> Back to docs</a>
      </footer>
    </article>
  </div>`;

let wired = false;

export function mountLearnings(container: HTMLElement): void {
  container.innerHTML = LEARNINGS_HTML;
  if (wired) return;
  wired = true;
  wireNav(container);
}

// Chapter nav: smooth-scroll on click + scrollspy highlight, mirroring the docs
// view. Same behaviour, scoped to `#learnings/ch<n>` deep links.
function wireNav(container: HTMLElement): void {
  const links = Array.from(container.querySelectorAll<HTMLAnchorElement>(".docs-nav-link"));
  const byId = new Map(links.map((l) => [l.dataset.target ?? "", l]));
  const items = Array.from(container.querySelectorAll<HTMLElement>(".tl-item"));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  for (const link of links) {
    link.addEventListener("click", (e) => {
      const id = link.dataset.target ?? "";
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      history.replaceState(null, "", `#learnings/${id}`);
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
  for (const it of items) observer.observe(it);

  const deep = location.hash.match(/^#learnings\/(.+)$/);
  if (deep) {
    const target = document.getElementById(deep[1]);
    if (target) {
      target.scrollIntoView({ behavior: "auto", block: "start" });
      setActive(deep[1]);
    }
  } else {
    setActive(items[0]?.id ?? "");
  }
}
