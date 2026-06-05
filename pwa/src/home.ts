// The home hub (default view, no hash) — the one place you read the brain:
//
//   • stat tiles: how many sources, across how many top-level domains
//   • a search box: hybrid recall over every source (GET /api/recall)
//   • a source map: the full path tree of ingested sources (GET /api/map)
//
// Both reads go through the owner read-proxy in server/index.ts; the PWA never
// writes. Search and the map used to be separate hash routes — they're embedded
// here now. All brain-returned strings (titles, paths, recall text) are escaped
// before they touch innerHTML — source data is never markup.

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

interface MapSource {
  path?: string;
  title?: string;
}

interface RecallChunk {
  heading?: string;
  text?: string;
  score?: number;
  path?: string;
}

const CAPTURE_NOTE = `
  <p class="cap-note">
    Free-text capture is paused — the brain ingests <strong>sources</strong>
    (Notion pages / docs), not raw text. See <a href="#docs">docs</a> for how it
    works today.
  </p>`;

export function mountHome(container: HTMLElement): void {
  container.innerHTML = `<p class="home-status">Loading the brain…</p>`;
  void loadHome(container);
}

async function loadHome(container: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/map`);
    if (!res.ok) {
      renderUnavailable(container, `HTTP ${res.status}`);
      return;
    }
    const data = (await res.json()) as { sources?: MapSource[] };
    renderHome(container, Array.isArray(data.sources) ? data.sources : []);
  } catch (err) {
    renderUnavailable(container, String(err));
  }
}

function renderUnavailable(container: HTMLElement, detail: string): void {
  container.innerHTML = `
    <div class="home-hero">
      <p class="home-lead">Couldn't reach the brain (${esc(detail)}).</p>
    </div>
    ${CAPTURE_NOTE}`;
}

// Top-level path segment = "domain" (e.g. "Job Hunting/Target role" → "Job
// Hunting"). Empty-path sources count as "Uncategorized".
function domainOf(path: string): string {
  const trimmed = path.trim();
  return trimmed ? trimmed.split("/")[0] : "Uncategorized";
}

function renderHome(container: HTMLElement, sources: MapSource[]): void {
  if (sources.length === 0) {
    container.innerHTML = `
      <div class="home-hero">
        <p class="home-lead">The brain is empty — no sources ingested yet.</p>
      </div>
      <a class="home-discover" href="#discover">Discover Notion pages →</a>
      ${CAPTURE_NOTE}`;
    return;
  }

  const domains = new Set(sources.map((s) => domainOf(s.path ?? "")));
  const nSrc = sources.length;
  const nDom = domains.size;

  container.innerHTML = `
    <div class="home-stats">
      <div class="stat">
        <span class="stat-num">${nSrc}</span>
        <span class="stat-label">Source${nSrc === 1 ? "" : "s"}</span>
      </div>
      <div class="stat">
        <span class="stat-num">${nDom}</span>
        <span class="stat-label">Domain${nDom === 1 ? "" : "s"}</span>
      </div>
    </div>

    <form class="home-search" id="home-search-form" role="search">
      <input id="home-q" type="search" placeholder="Search the brain…" autocomplete="off" />
      <button type="submit">Recall</button>
    </form>

    <div class="home-results" hidden></div>

    <a class="home-discover" href="#discover">Discover Notion pages →</a>

    <section class="home-map">
      <h2>Sources</h2>
      <div class="src-tree">${renderTree(sources)}</div>
    </section>

    ${CAPTURE_NOTE}`;

  wireSearch(container);
}

// --- Source map: path tree -------------------------------------------------

interface TreeNode {
  name: string; // last path segment (the display label for a folder)
  title?: string; // set when a real source lives exactly at this path
  children: Map<string, TreeNode>;
}

function buildTree(sources: MapSource[]): TreeNode {
  const root: TreeNode = { name: "", children: new Map() };
  for (const s of sources) {
    const path = (s.path ?? "").trim();
    const segs = path ? path.split("/") : [];
    if (segs.length === 0) {
      // Empty-path source: hang it directly off root, keyed by title.
      const title = s.title || "(untitled)";
      root.children.set(`~${title}`, { name: title, title, children: new Map() });
      continue;
    }
    let node = root;
    for (const seg of segs) {
      let next = node.children.get(seg);
      if (!next) {
        next = { name: seg, children: new Map() };
        node.children.set(seg, next);
      }
      node = next;
    }
    // A source lives exactly here — give it its title (distinguishes it from a
    // pure structural folder synthesized from a deeper path).
    node.title = s.title || node.name;
  }
  return root;
}

function renderTree(sources: MapSource[]): string {
  const root = buildTree(sources);
  return `<ul class="src-list">${renderChildren(root)}</ul>`;
}

function renderChildren(node: TreeNode): string {
  const kids = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));
  return kids.map(renderNode).join("");
}

function renderNode(node: TreeNode): string {
  const isSource = node.title !== undefined;
  const label = esc(node.title ?? node.name);
  const childHTML = node.children.size ? `<ul class="src-list">${renderChildren(node)}</ul>` : "";
  return `
    <li class="src-node ${isSource ? "is-source" : "is-folder"}">
      <span class="src-label">${label}</span>
      ${childHTML}
    </li>`;
}

// --- Embedded recall search ------------------------------------------------

function wireSearch(container: HTMLElement): void {
  const form = container.querySelector<HTMLFormElement>("#home-search-form");
  const input = container.querySelector<HTMLInputElement>("#home-q");
  const results = container.querySelector<HTMLDivElement>(".home-results");
  const map = container.querySelector<HTMLElement>(".home-map");
  const button = container.querySelector<HTMLButtonElement>("#home-search-form button");
  if (!form || !input || !results || !map || !button) return;

  const showMap = () => {
    results.hidden = true;
    results.innerHTML = "";
    map.hidden = false;
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) {
      showMap();
      return;
    }
    map.hidden = true;
    results.hidden = false;
    results.innerHTML = `<p class="home-status">Searching…</p>`;
    button.disabled = true;
    void runRecall(q, results).finally(() => {
      button.disabled = false;
    });
  });

  // Delegated "clear" — restore the map view.
  results.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t.classList.contains("home-clear")) {
      e.preventDefault();
      input.value = "";
      showMap();
      input.focus();
    }
  });
}

async function runRecall(q: string, results: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/recall?q=${encodeURIComponent(q)}&k=8`);
    if (!res.ok) {
      results.innerHTML = `${clearBar(q)}<p class="home-status">Recall failed (${esc(res.status)}).</p>`;
      return;
    }
    const data = (await res.json()) as { chunks?: RecallChunk[] };
    const chunks = Array.isArray(data.chunks) ? data.chunks : [];
    if (chunks.length === 0) {
      results.innerHTML = `${clearBar(q)}<p class="home-status">No results for “${esc(q)}”.</p>`;
      return;
    }
    results.innerHTML = clearBar(q) + chunks.map(renderHit).join("");
  } catch (err) {
    results.innerHTML = `${clearBar(q)}<p class="home-status">Could not reach the brain (${esc(err)}).</p>`;
  }
}

function clearBar(q: string): string {
  return `
    <div class="home-results-head">
      <span class="home-results-q">Results for “${esc(q)}”</span>
      <a class="home-clear" href="#">Clear</a>
    </div>`;
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
