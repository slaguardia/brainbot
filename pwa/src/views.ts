// Owner read-views over the brain: a recall search box (#search) and the source
// map (#map). The PWA is the OWNER surface, so reading the brain here is fine —
// both views GET through the thin proxy in server/index.ts (/api/recall,
// /api/map), which forwards to the brain. They never write.
//
// Reached via the `#search` / `#map` hash routes; the router in main.ts mounts
// each lazily on first visit and toggles it against the capture screen. The
// topbar reuses the docs view's class names (docs-topbar, brand, docs-back,
// docs-cross) so the chrome stays consistent.
//
// All brain-returned text is escaped before it lands in innerHTML — recall hits
// and source titles are data, never markup.

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Minimal styling for the read-view bits. Scoped under the view ids so it can't
// leak into the docs/capture chrome it borrows class names from.
const VIEW_STYLE = `
  <style>
    #search-view .rv-body, #map-view .rv-body { max-width: 760px; margin: 0 auto; padding: 1.25rem 1rem 4rem; }
    #search-view h1, #map-view h1 { font-size: 1.4rem; margin: 0 0 .35rem; }
    #search-view .rv-lead, #map-view .rv-lead { color: #8b94a6; margin: 0 0 1.25rem; font-size: .95rem; }
    .rv-form { display: flex; gap: .5rem; margin-bottom: 1.25rem; }
    .rv-form input { flex: 1; padding: .6rem .75rem; border-radius: 8px; border: 1px solid #2d3243; background: #14171f; color: #e8eaf0; font-size: 1rem; }
    .rv-form button { padding: .6rem 1.1rem; border-radius: 8px; border: 1px solid #8b6dff; background: rgba(139,109,255,0.12); color: #c2b8ff; font-size: 1rem; cursor: pointer; }
    .rv-form button:disabled { opacity: .5; cursor: default; }
    .rv-status { color: #8b94a6; font-size: .9rem; }
    .rv-hit { border: 1px solid #2d3243; border-radius: 10px; padding: .85rem 1rem; margin-bottom: .75rem; background: #11141b; }
    .rv-hit-head { display: flex; align-items: baseline; justify-content: space-between; gap: .75rem; margin-bottom: .4rem; }
    .rv-hit-heading { font-weight: 600; color: #e8eaf0; }
    .rv-hit-score { color: #c2b8ff; font-size: .8rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .rv-hit-text { color: #c7d2e8; font-size: .92rem; line-height: 1.5; white-space: pre-wrap; }
    .rv-hit-path { color: #6c7484; font-size: .78rem; margin-top: .45rem; }
    .rv-map-item { display: flex; align-items: baseline; gap: .6rem; padding: .5rem .25rem; border-bottom: 1px solid #1c2030; }
    .rv-map-title { color: #e8eaf0; }
    .rv-map-path { color: #6c7484; font-size: .78rem; }
  </style>`;

function topbar(label: string): string {
  return `
    <div class="docs-topbar">
      <a class="docs-back" href="#" aria-label="Back to capture">
        <span class="docs-back-arrow" aria-hidden="true">←</span> Capture
      </a>
      <span class="brand" aria-label="brain">brain</span>
      <a class="docs-cross" href="${esc(label === "search" ? "#map" : "#search")}" aria-label="${label === "search" ? "Source map" : "Search the brain"}">${
        label === "search" ? "Map&nbsp;→" : "Search&nbsp;→"
      }</a>
    </div>`;
}

// --- Recall search (#search) -------------------------------------------------

interface RecallChunk {
  heading?: string;
  text?: string;
  score?: number;
  path?: string;
}

export function mountSearch(container: HTMLElement): void {
  container.innerHTML = `
    ${VIEW_STYLE}
    ${topbar("search")}
    <div class="rv-body">
      <h1>Search the brain</h1>
      <p class="rv-lead">Hybrid recall over every ingested source — cosine + full-text, fused.</p>
      <form class="rv-form" id="rv-search-form">
        <input id="rv-q" type="search" placeholder="Ask the brain…" autocomplete="off" />
        <button id="rv-go" type="submit">Recall</button>
      </form>
      <div class="rv-results"><p class="rv-status">Enter a query to search.</p></div>
    </div>`;

  const form = container.querySelector<HTMLFormElement>("#rv-search-form");
  const input = container.querySelector<HTMLInputElement>("#rv-q");
  const button = container.querySelector<HTMLButtonElement>("#rv-go");
  const results = container.querySelector<HTMLDivElement>(".rv-results");
  if (!form || !input || !button || !results) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) {
      results.innerHTML = `<p class="rv-status">Enter a query to search.</p>`;
      return;
    }
    button.disabled = true;
    results.innerHTML = `<p class="rv-status">Searching…</p>`;
    void runRecall(q, results).finally(() => {
      button.disabled = false;
    });
  });
}

async function runRecall(q: string, results: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/recall?q=${encodeURIComponent(q)}&k=8`);
    if (!res.ok) {
      results.innerHTML = `<p class="rv-status">Recall failed (${esc(res.status)}).</p>`;
      return;
    }
    const data = (await res.json()) as { chunks?: RecallChunk[] };
    const chunks = Array.isArray(data.chunks) ? data.chunks : [];
    if (chunks.length === 0) {
      results.innerHTML = `<p class="rv-status">No results.</p>`;
      return;
    }
    results.innerHTML = chunks.map(renderHit).join("");
  } catch (err) {
    results.innerHTML = `<p class="rv-status">Could not reach the brain (${esc(err)}).</p>`;
  }
}

function renderHit(c: RecallChunk): string {
  const score = typeof c.score === "number" ? c.score.toFixed(4) : "";
  return `
    <div class="rv-hit">
      <div class="rv-hit-head">
        <span class="rv-hit-heading">${esc(c.heading) || "(untitled)"}</span>
        ${score ? `<span class="rv-hit-score">${esc(score)}</span>` : ""}
      </div>
      <div class="rv-hit-text">${esc(c.text)}</div>
      ${c.path ? `<div class="rv-hit-path">${esc(c.path)}</div>` : ""}
    </div>`;
}

// --- Source map (#map) -------------------------------------------------------

interface MapSource {
  path?: string;
  title?: string;
}

export function mountMap(container: HTMLElement): void {
  container.innerHTML = `
    ${VIEW_STYLE}
    ${topbar("map")}
    <div class="rv-body">
      <h1>Source map</h1>
      <p class="rv-lead">Every source the brain has ingested.</p>
      <div class="rv-tree"><p class="rv-status">Loading…</p></div>
    </div>`;

  const tree = container.querySelector<HTMLDivElement>(".rv-tree");
  if (!tree) return;
  void loadMap(tree);
}

async function loadMap(tree: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/map`);
    if (!res.ok) {
      tree.innerHTML = `<p class="rv-status">Map failed (${esc(res.status)}).</p>`;
      return;
    }
    const data = (await res.json()) as { sources?: MapSource[] };
    const sources = Array.isArray(data.sources) ? data.sources : [];
    if (sources.length === 0) {
      tree.innerHTML = `<p class="rv-status">No sources ingested yet.</p>`;
      return;
    }
    tree.innerHTML = sources.map(renderSource).join("");
  } catch (err) {
    tree.innerHTML = `<p class="rv-status">Could not reach the brain (${esc(err)}).</p>`;
  }
}

function renderSource(s: MapSource): string {
  return `
    <div class="rv-map-item">
      <span class="rv-map-title">${esc(s.title) || "(untitled)"}</span>
      ${s.path ? `<span class="rv-map-path">${esc(s.path)}</span>` : ""}
    </div>`;
}
