// The home hub (default view, no hash) — the one place you read the brain:
//
//   • a header: title + a meta line (how many sources, across how many top-level
//     domains, plus the Notion sync status)
//   • a search box: hybrid recall over every source (toolkit recall())
//   • a source map: the full path tree of ingested sources (toolkit map())
//
// Both reads use @brainbot/web-toolkit/brain, which calls the owner read-proxy
// (/api/brain/recall|map) in server/index.ts. Search and the map used to be
// separate hash routes — they're embedded here now. All brain-returned strings
// (titles, paths, recall text) are escaped before they touch innerHTML — source
// data is never markup.
//
// The meta line carries a Notion sync status: after the map renders, a
// background check (discover.ts's shared page list + staleness rule) reports
// "current with Notion" or offers one manual re-pull of the changed pages —
// detection is automatic, re-pulling is always the human's click.

import { recall, map, type Chunk, type Health, type Source } from "@brainbot/web-toolkit/brain";

import { fetchNotionPages, isStale, type NotionPage } from "./discover";

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

type MapSource = Pick<Source, "id" | "path" | "title" | "health">;
type RecallChunk = Pick<Chunk, "heading" | "text" | "score" | "path">;

// A note-legibility badge for a source: the 0–100 score, colour-tiered, with its
// actionable reasons in the tooltip and a link to the per-source legibility view
// (raw-vs-rewrite diff + actions). Empty string for un-analyzed sources (health
// null) so the layer is invisible when off.
function healthBadge(id: string | undefined, health: Health | null | undefined): string {
  if (!health) return "";
  const score = Math.round(health.score);
  const tier = score >= 70 ? "good" : score >= 40 ? "fair" : "poor";
  const reasons = health.notes.length
    ? `Legibility ${score}/100 — ${health.notes.join("; ")}`
    : `Legibility ${score}/100 — already legible to agents.`;
  const href = id ? `#legibility/${encodeURIComponent(id)}` : "#docs";
  return `<a class="src-health is-${tier}" href="${href}" title="${esc(reasons)}">${score}</a>`;
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
    const sources = await map();
    renderHome(container, Array.isArray(sources) ? sources : []);
  } catch (err) {
    renderUnavailable(container, String(err));
  }
}

function renderUnavailable(container: HTMLElement, detail: string): void {
  container.innerHTML = `
    <header class="page-head">
      <h1 class="page-title">Your brain</h1>
      <p class="home-lead">Couldn't reach the brain (${esc(detail)}).</p>
    </header>
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
      <header class="page-head">
        <h1 class="page-title">Your brain</h1>
        <p class="home-lead">The brain is empty — no sources ingested yet.</p>
      </header>
      <a class="home-discover" href="#discover">Discover Notion pages →</a>
      ${CAPTURE_NOTE}`;
    return;
  }

  const domains = new Set(sources.map((s) => domainOf(s.path ?? "")));
  const nSrc = sources.length;
  const nDom = domains.size;

  container.innerHTML = `
    <header class="page-head">
      <h1 class="page-title">Your brain</h1>
      <p class="home-meta">
        <span>${nSrc} source${nSrc === 1 ? "" : "s"}</span>
        <span class="home-sep">·</span>
        <span>${nDom} domain${nDom === 1 ? "" : "s"}</span>
        <span class="home-sep">·</span>
        <span class="home-sync">checking Notion…</span>
      </p>
    </header>

    <form class="home-search" id="home-search-form" role="search">
      <input id="home-q" type="search" placeholder="Search the brain…" autocomplete="off" />
      <button type="submit">Recall</button>
    </form>

    <div class="home-results" hidden></div>

    <section class="home-map">
      <div class="home-map-head">
        <h2>Sources</h2>
        <a class="home-discover" href="#discover">Discover Notion pages →</a>
      </div>
      <div class="src-tree">${renderTree(sources)}</div>
    </section>

    ${CAPTURE_NOTE}`;

  wireSearch(container);
  void checkSync(container);
}

// --- Notion sync status ------------------------------------------------------

async function checkSync(container: HTMLElement): Promise<void> {
  const el = container.querySelector<HTMLElement>(".home-sync");
  if (!el) return;
  let stale: NotionPage[];
  try {
    stale = (await fetchNotionPages()).filter(isStale);
  } catch {
    // The status is an enhancement — a Notion failure never breaks home.
    // Drop the leading "·" separator with it so the meta line stays clean.
    el.previousElementSibling?.remove();
    el.remove();
    return;
  }
  if (stale.length === 0) {
    el.textContent = "current with Notion";
    el.classList.add("is-current");
    return;
  }
  el.innerHTML = `${stale.length} changed in Notion <button class="disc-resync" type="button">re-pull</button>`;
  el.querySelector("button")!.addEventListener("click", function (this: HTMLButtonElement) {
    void repull(container, this, stale);
  });
}

// Sequential re-pull of the stale pages (same wipe-replace /api/ingest path the
// discover view uses), then a full home reload: the map picks up any new
// titles/paths and the re-run sync check — against the cache the live re-fetch
// just refreshed — reports what's left (a failed page simply stays counted).
async function repull(
  container: HTMLElement,
  btn: HTMLButtonElement,
  stale: NotionPage[],
): Promise<void> {
  btn.disabled = true;
  for (let i = 0; i < stale.length; i++) {
    btn.textContent = `re-pulling ${i + 1}/${stale.length}…`;
    try {
      await fetch(`/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: stale[i].url }),
      });
    } catch {
      // Page stays stale; the re-rendered status counts it again.
    }
  }
  try {
    await fetchNotionPages(true);
  } catch {
    // Notion died mid-flow: the cache still holds the pre-pull list, so the
    // re-rendered status may overcount until the next successful sweep.
  }
  void loadHome(container);
}

// --- Source map: path tree -------------------------------------------------

interface TreeNode {
  name: string; // last path segment (the display label for a folder)
  title?: string; // set when a real source lives exactly at this path
  id?: string; // set alongside title — the source's stable id (for the legibility link)
  health?: Health | null; // set alongside title — the source's legibility signal
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
      root.children.set(`~${title}`, { name: title, title, id: s.id, health: s.health, children: new Map() });
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
    // pure structural folder synthesized from a deeper path), id, and health.
    node.title = s.title || node.name;
    node.id = s.id;
    node.health = s.health;
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
  const badge = isSource ? healthBadge(node.id, node.health) : "";
  const childHTML = node.children.size ? `<ul class="src-list">${renderChildren(node)}</ul>` : "";
  return `
    <li class="src-node ${isSource ? "is-source" : "is-folder"}">
      <span class="src-label">${label}</span>${badge}
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
    const chunks: RecallChunk[] = await recall(q, 8);
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
