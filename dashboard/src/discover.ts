// The Notion pages view (`#discover`) — the one place you *browse and manage*
// what's in the brain. GET /api/notion/pages returns every shared page (children
// included) as flat {id, title, parent_id, last_edited_time, url, ingested,
// ingested_last_edited} facts; this view builds the parent/child tree and offers
// a per-page "pull" action that POSTs the page's URL to /api/ingest (the brain's
// existing write path), a per-page "remove" action that DELETEs an ingested
// page's source from the brain (/api/sources/{id}), plus ONE bulk "re-pull"
// button for ingested pages whose Notion copy moved past what the brain captured.
//
// Two things folded in here from the old home hub (which is now just search):
//   • a summary strip — page / in-brain / changed counts + an overall legibility
//     readout, replacing the old plain mono counts line;
//   • the note-legibility badge on each in-brain row. A brain source's id IS its
//     Notion page uuid (see brain/api.py: ingested = page.id in sources), so
//     map()'s per-source health joins straight onto this tree by id — no home
//     tree to keep in step anymore.
//
// A filter toolbar (text + "not in brain" / "changed" toggles) narrows a big
// shared workspace to what you're looking for. All Notion-returned strings
// (titles) are escaped before they touch innerHTML.

import { button, modal, toast } from "@brainbot/web-toolkit/components";
import { map, type Health } from "@brainbot/web-toolkit/brain";

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

interface NotionPage {
  id?: string;
  kind?: string; // 'page' | 'database' — database rows are pages parented by a database
  title?: string;
  parent_id?: string | null;
  last_edited_time?: string | null;
  url?: string;
  ingested?: boolean;
  ingested_last_edited?: string | null; // origin edit time the brain captured at ingest
  auto_expand?: boolean; // opted in to auto-pulling new descendants as they appear
}

// A pulled page is stale when Notion's copy moved past the one the brain
// captured at ingest — or when the brain recorded no edit time at all (sources
// ingested before that was stored), where "possibly stale" must mean re-pull.
function isStale(p: NotionPage): boolean {
  if (!p.ingested || !p.url || !p.last_edited_time) return false;
  if (!p.ingested_last_edited) return true;
  return new Date(p.last_edited_time) > new Date(p.ingested_last_edited);
}

// --- discovery cache ----------------------------------------------------------
// The Notion sweep takes a few seconds, so the page list is cached in
// sessionStorage: every (re)visit renders instantly from cache, the Refresh
// button is the explicit re-fetch, and pulls patch the cached entries in place.

// v2: entries grew `ingested_last_edited` — a v1 cache would mark every
// ingested page stale until the next real fetch.
const CACHE_KEY = "discover-pages-v2";

let currentPages: NotionPage[] = [];
let fetchedAt = 0;

// Per-source legibility signal, keyed by the page uuid (== the brain source id).
// Filled by loadHealth() from map(); overlaid onto in-brain rows. Empty until
// that first read resolves — the badges are an enhancement, never blocking.
let healthById = new Map<string, Health>();

// The active filter — persisted across re-renders (a pull re-renders the whole
// body, and we don't want the filter to reset under the user).
const filterState = { text: "", onlyNew: false, onlyChanged: false, onlyPoor: false };

function readCache(): NotionPage[] | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as { at?: number; pages?: NotionPage[] };
    if (!Array.isArray(data.pages)) return null;
    fetchedAt = data.at ?? 0;
    return data.pages;
  } catch {
    return null;
  }
}

function writeCache(pages: NotionPage[], at: number = Date.now()): void {
  // `at` defaults to now for a fresh fetch; an in-place patch (a pull flipping
  // one ingested flag) passes the original fetch time — the list isn't newer.
  fetchedAt = at;
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at, pages }));
  } catch {
    // Quota/private-mode failure: cache is an optimization, never a requirement.
  }
}

export function mountDiscover(container: HTMLElement): void {
  // The shared header/nav chrome is rendered by the toolkit shell (mountApp);
  // this view renders only its body into the content region.
  container.innerHTML = `
    <section class="home discover">
      <div class="disc-head">
        <div class="disc-head-text">
          <a class="disc-back" href="#">← Search the brain</a>
          <h2>Notion pages</h2>
          <p class="disc-sub">
            Every page shared with the integration. Pull the ones you want into the brain.
          </p>
        </div>
        <a class="disc-refresh" href="#discover">Refresh</a>
      </div>
      <div class="disc-body"><p class="home-status">Asking Notion…</p></div>
    </section>`;
  const body = container.querySelector<HTMLElement>(".disc-body")!;
  container.querySelector<HTMLAnchorElement>(".disc-refresh")!.addEventListener("click", (e) => {
    e.preventDefault();
    body.innerHTML = `<p class="home-status">Asking Notion…</p>`;
    void loadPages(body);
    void loadHealth(body);
  });
  // Delegated handlers, attached ONCE — renders replace body.innerHTML, so a
  // per-render listener would stack across refreshes and double-fire ingest.
  wireIngest(body); // clicks: pull / remove / filter toggles / open-in-Notion
  wireFilter(body); // input: the filter text box
  const cached = readCache();
  if (cached) {
    currentPages = cached;
    renderPages(body, cached);
  } else {
    void loadPages(body);
  }
  // Legibility badges load independently of the page list (they come from the
  // brain's map(), not Notion) and paint in when ready.
  void loadHealth(body);
}

async function loadPages(body: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/notion/pages`);
    const data = (await res.json()) as { pages?: NotionPage[]; error?: string };
    if (!res.ok) {
      body.innerHTML = `<p class="home-status">Discovery failed: ${esc(data.error ?? `HTTP ${res.status}`)}</p>`;
      return;
    }
    const pages = Array.isArray(data.pages) ? data.pages : [];
    currentPages = pages;
    writeCache(pages);
    renderPages(body, pages);
  } catch (err) {
    body.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(err)}).</p>`;
  }
}

// The per-source legibility signal, from the brain's map(). Best-effort: a
// failure just leaves the badges off — the page list stands on its own.
async function loadHealth(body: HTMLElement): Promise<void> {
  try {
    const sources = await map();
    const next = new Map<string, Health>();
    for (const s of sources) if (s.health) next.set(s.id, s.health);
    healthById = next;
    applyHealth(body);
    // The "Poor legibility" filter gates on health that arrives after the first
    // render — re-run the tree so a filter toggled before it loaded picks it up.
    if (filterState.onlyPoor) renderTree(body);
  } catch {
    // Health is an enhancement; never surface its failure over the page list.
  }
}

// --- note-legibility badge ---------------------------------------------------

// A note-legibility badge for an in-brain page: the 0–100 score, colour-tiered,
// with its actionable reasons in the tooltip and a link to the per-source
// legibility view (raw-vs-rewrite diff + actions). Empty string when the layer
// hasn't analyzed the page yet, so the column is invisible until it has.
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

// Overlay the loaded health onto the rendered tree without re-rendering it —
// so the branches you've expanded and the filter box you're typing in stay put.
// Fills each in-brain row's health slot (keyed by data-health-for) and the
// summary's avg-legibility + poor-count stats.
function applyHealth(body: HTMLElement): void {
  for (const [id, h] of healthById) {
    const cell = body.querySelector<HTMLElement>(`[data-health-for="${id}"]`);
    if (cell) cell.innerHTML = healthBadge(id, h);
  }
  const stat = body.querySelector<HTMLElement>(".disc-health-stat");
  if (stat) {
    const hs = healthStats();
    if (hs) {
      const tier = hs.avg >= 70 ? "good" : hs.avg >= 40 ? "fair" : "poor";
      // Show coverage only when not every in-brain page has been scored — an
      // average over 2 of 40 pages shouldn't read as the whole brain's health.
      const cov = hs.scored < hs.total ? ` · ${hs.scored}/${hs.total} scored` : "";
      stat.className = `disc-stat disc-health-stat is-${tier}`;
      stat.innerHTML = `<span class="disc-stat-n">${hs.avg}</span><span class="disc-stat-l">avg legibility${cov}</span>`;
      stat.removeAttribute("hidden");
    }
  }
  const poorStat = body.querySelector<HTMLElement>(".disc-poor-stat");
  if (poorStat) {
    const n = poorCount();
    if (n > 0) {
      poorStat.innerHTML = `<span class="disc-stat-n">${n}</span><span class="disc-stat-l">poor</span>`;
      poorStat.removeAttribute("hidden");
    } else {
      poorStat.setAttribute("hidden", "");
      poorStat.innerHTML = "";
    }
  }
}

// Legibility rollups over the in-brain pages the layer has scored (databases
// have no document body, so they're excluded). `total` counts scorable in-brain
// pages whether scored yet or not, so the summary can show coverage. Null when
// nothing's been analyzed.
function healthStats(): { avg: number; scored: number; total: number } | null {
  let sum = 0;
  let scored = 0;
  let total = 0;
  for (const p of currentPages) {
    if (!p.ingested || p.kind === "database" || !p.id) continue;
    total++;
    const h = healthById.get(p.id);
    if (h) {
      sum += h.score;
      scored++;
    }
  }
  return scored ? { avg: Math.round(sum / scored), scored, total } : null;
}

// A scored in-brain page below the "poor" tier (score < 40 — the red badge). The
// summary counts these; the "Poor legibility" filter isolates them.
function isPoor(p: NotionPage): boolean {
  if (!p.ingested || p.kind === "database" || !p.id) return false;
  const h = healthById.get(p.id);
  return !!h && h.score < 40;
}

function poorCount(): number {
  let n = 0;
  for (const p of currentPages) if (isPoor(p)) n++;
  return n;
}

// --- parent/child tree -------------------------------------------------------

interface PageNode {
  page: NotionPage;
  children: PageNode[];
}

// The last-built FULL tree + its by-id index. Actions (pull-all, remove-all)
// resolve a clicked page's real subtree through nodeById, so they operate on the
// whole workspace even when the filter is showing a subset.
let nodeById = new Map<string, PageNode>();
let fullRoots: PageNode[] = [];

// Roots = pages whose parent isn't itself a visible page (workspace/database/
// block parents, or a parent page that wasn't shared with the integration).
function buildTree(pages: NotionPage[]): PageNode[] {
  const nodes = new Map<string, PageNode>();
  for (const p of pages) {
    if (p.id) nodes.set(p.id, { page: p, children: [] });
  }
  nodeById = nodes;
  const roots: PageNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.page.parent_id ? nodes.get(node.page.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const byTitle = (a: PageNode, b: PageNode) =>
    (a.page.title || "").localeCompare(b.page.title || "");
  const sortDeep = (list: PageNode[]) => {
    list.sort(byTitle);
    for (const n of list) sortDeep(n.children);
  };
  sortDeep(roots);
  return roots;
}

function renderPages(body: HTMLElement, pages: NotionPage[]): void {
  if (pages.length === 0) {
    body.innerHTML = `
      <p class="home-status">
        Notion returned no pages — share pages with the integration in Notion
        (Connections → your integration) and refresh.
      </p>`;
    return;
  }
  fullRoots = buildTree(pages); // sets nodeById (the full-tree index)
  body.innerHTML = `${renderSummary(pages)}${renderToolbar()}<div class="disc-tree-wrap"></div>`;
  renderTree(body); // renders the (possibly filtered) tree + overlays health
}

// The summary strip: page / in-brain / changed stat tiles, an overall-legibility
// tile (filled by applyHealth once map() resolves), and the sync time + the one
// bulk re-pull action. Replaces the old single mono counts line.
function renderSummary(pages: NotionPage[]): string {
  const real = pages.filter((p) => p.kind !== "database");
  const n = real.length;
  const nIn = real.filter((p) => p.ingested).length;
  const nStale = real.filter(isStale).length;
  const at = fetchedAt
    ? `synced ${new Date(fetchedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : "";
  const changedStat = nStale
    ? `<div class="disc-stat is-changed"><span class="disc-stat-n">${nStale}</span><span class="disc-stat-l">changed</span></div>`
    : "";
  // One bulk action — re-pull every ingested page whose Notion copy moved. The
  // handler recomputes the stale set from currentPages on click.
  const resync = nStale
    ? `<button class="disc-resync" type="button">Re-pull ${nStale} changed</button>`
    : "";
  return `
    <div class="disc-summary">
      <div class="disc-stats">
        <div class="disc-stat"><span class="disc-stat-n">${n}</span><span class="disc-stat-l">page${n === 1 ? "" : "s"}</span></div>
        <div class="disc-stat is-in"><span class="disc-stat-n">${nIn}</span><span class="disc-stat-l">in brain</span></div>
        ${changedStat}
        <div class="disc-stat disc-health-stat" hidden></div>
        <div class="disc-stat disc-poor-stat" hidden></div>
      </div>
      <div class="disc-summary-side">
        ${resync}
        ${at ? `<span class="disc-synced">${at}</span>` : ""}
      </div>
    </div>`;
}

function renderToolbar(): string {
  const f = filterState;
  return `
    <div class="disc-toolbar">
      <input id="disc-filter" class="tk-input disc-filter" type="search"
        placeholder="Filter pages…" autocomplete="off" value="${esc(f.text)}" />
      <div class="disc-toggles">
        <button class="disc-toggle${f.onlyNew ? " is-on" : ""}" data-toggle="new" type="button" aria-pressed="${f.onlyNew}">Not in brain</button>
        <button class="disc-toggle${f.onlyChanged ? " is-on" : ""}" data-toggle="changed" type="button" aria-pressed="${f.onlyChanged}">Changed</button>
        <button class="disc-toggle${f.onlyPoor ? " is-on" : ""}" data-toggle="poor" type="button" aria-pressed="${f.onlyPoor}">Poor legibility</button>
      </div>
    </div>`;
}

function filterActive(): boolean {
  return !!(
    filterState.text.trim() ||
    filterState.onlyNew ||
    filterState.onlyChanged ||
    filterState.onlyPoor
  );
}

// Whether a page itself satisfies the active filter. Text matches its title;
// the toggles gate on real (non-database) pages — "not in brain" = pullable and
// not yet ingested, "changed" = ingested but drifted.
function pageMatches(p: NotionPage): boolean {
  const text = filterState.text.trim().toLowerCase();
  if (text && !(p.title ?? "").toLowerCase().includes(text)) return false;
  if (filterState.onlyNew && (p.kind === "database" || p.ingested)) return false;
  if (filterState.onlyChanged && !isStale(p)) return false;
  if (filterState.onlyPoor && !isPoor(p)) return false;
  return true;
}

// Prune the full tree to the filter: a node survives if it matches, or if any
// descendant survives (so a matching page keeps its ancestors for context).
function filterNode(node: PageNode): PageNode | null {
  const kids = node.children.map(filterNode).filter((n): n is PageNode => n !== null);
  if (kids.length || pageMatches(node.page)) return { page: node.page, children: kids };
  return null;
}

// Render (or re-render) just the tree region — the toolbar and summary stay put,
// so the filter box keeps focus while you type. When a filter is active, every
// branch renders open so matches deep in the workspace are actually visible.
function renderTree(body: HTMLElement): void {
  const wrap = body.querySelector<HTMLElement>(".disc-tree-wrap");
  if (!wrap) return;
  const active = filterActive();
  const view = active
    ? fullRoots.map(filterNode).filter((n): n is PageNode => n !== null)
    : fullRoots;
  if (view.length === 0) {
    wrap.innerHTML = `<p class="home-status">No pages match the filter.</p>`;
    return;
  }
  wrap.innerHTML = `<ul class="src-list disc-tree">${view.map((n) => renderNode(n, active)).join("")}</ul>`;
  applyHealth(body); // fill the freshly rendered rows' health slots
}

// One row, laid out as columns so the eye can scan down: the title grows to fill
// the middle (with a hover-revealed open-in-Notion link), then fixed-width cells
// hug the right edge — meta (edited date / row count), status (pull · in brain ·
// pull all), health (legibility score), and remove (remove · remove all). The
// cells right-align, so dates line up under dates and buttons under buttons.
function rowHTML(node: PageNode): string {
  const p = node.page;
  const isDb = p.kind === "database";
  const id = esc(p.id ?? "");
  const url = esc(p.url ?? "");
  const title = esc(p.title || "(untitled)");
  // Auto-expand opt-in — a switch in its own right-hand cell, only where it
  // applies: a database, or an in-brain page that already has sub-pages (a leaf
  // page has nothing to expand).
  const canExpand = isDb || (!!p.ingested && node.children.length > 0);
  const expandOn = !!p.auto_expand;
  const kind = isDb ? "rows" : "sub-pages";
  const expand = canExpand
    ? `<button class="disc-switch${expandOn ? " is-on" : ""}" type="button" role="switch" aria-checked="${expandOn}" data-id="${id}" data-on="${expandOn ? "1" : "0"}" title="Auto-pull new ${kind} under this as they appear in Notion (opt-in)" aria-label="Auto-pull new ${kind}"><span class="disc-switch-knob"></span></button>`
    : "";
  let meta = ""; // a page's edited date, or a database's row count
  let status = ""; // pull · in brain · pull all
  let health = `<span class="disc-cell disc-cell-health"></span>`; // legibility score slot
  let remove = ""; // remove · remove all
  if (isDb) {
    const n = node.children.length;
    const pending = collectChildPages(node).length;
    const ingested = collectIngestedChildPages(node).length;
    meta = `${n} page${n === 1 ? "" : "s"}`;
    if (pending)
      status = `<button class="disc-pull-db" type="button" data-id="${id}">pull all ${pending}</button>`;
    if (ingested)
      remove = `<button class="disc-remove-db" type="button" data-id="${id}">remove all ${ingested}</button>`;
  } else {
    meta = p.last_edited_time ? esc(p.last_edited_time.slice(0, 10)) : "";
    if (p.ingested) {
      status = `<span class="disc-badge is-ingested">in brain</span>`;
      // The slot carries data-health-for so applyHealth can fill it later even
      // when map() hasn't resolved at first render.
      const badge = healthBadge(p.id, healthById.get(p.id ?? "") ?? null);
      health = `<span class="disc-cell disc-cell-health" data-health-for="${id}">${badge}</span>`;
      remove = `<button class="disc-remove" type="button" data-id="${id}" data-url="${url}" title="remove from the brain">remove</button>`;
    } else {
      status = `<button class="disc-pull" type="button" data-id="${id}" data-url="${url}">pull</button>`;
    }
  }
  return `
      ${isDb ? `<span class="disc-kind-db">db</span>` : ""}
      <span class="src-label">${title}</span>
      <span class="disc-cell disc-cell-meta">${meta}</span>
      <span class="disc-cell disc-cell-status">${status}</span>
      ${health}
      <span class="disc-cell disc-cell-expand">${expand}</span>
      <span class="disc-cell disc-cell-remove">${remove}</span>`;
}

function renderNode(node: PageNode, openAll = false): string {
  // The whole row opens the page in Notion on click (data-url); a leading caret
  // toggles expand. A parent renders as a native <details> (its open state is
  // driven by the caret, not the summary's default toggle, which the row-click
  // handler suppresses); collapsed by default keeps big databases from flooding
  // the view — unless a filter is active, when we open everything.
  const url = esc(node.page.url ?? "");
  if (node.children.length) {
    return `
    <li class="src-node is-source">
      <details class="disc-branch"${openAll ? " open" : ""}>
        <summary class="disc-row" data-url="${url}"><span class="disc-caret" aria-hidden="true"></span>${rowHTML(node)}</summary>
        <ul class="src-list">${node.children.map((c) => renderNode(c, openAll)).join("")}</ul>
      </details>
    </li>`;
  }
  return `
    <li class="src-node is-source">
      <span class="disc-row" data-url="${url}"><span class="disc-caret-spacer" aria-hidden="true"></span>${rowHTML(node)}</span>
    </li>`;
}

// --- filter wiring -----------------------------------------------------------

function wireFilter(body: HTMLElement): void {
  // Delegated so it survives full body re-renders. Typing only re-renders the
  // tree region (not the toolbar), so the input keeps focus. Debounced so a big
  // workspace isn't re-rendered on every keystroke.
  let timer: ReturnType<typeof setTimeout> | undefined;
  body.addEventListener("input", (e) => {
    const t = e.target as HTMLElement;
    if (t.id === "disc-filter") {
      filterState.text = (t as HTMLInputElement).value;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => renderTree(body), 120);
    }
  });
}

// --- selective pull ----------------------------------------------------------

function wireIngest(body: HTMLElement): void {
  body.addEventListener("click", (e) => {
    const btn = e.target as HTMLElement;
    if (btn.classList.contains("disc-toggle")) {
      // A filter toggle: flip its state, reflect it on the chip, re-render the
      // tree region only.
      e.preventDefault();
      const which = btn.getAttribute("data-toggle");
      if (which === "new") filterState.onlyNew = !filterState.onlyNew;
      if (which === "changed") filterState.onlyChanged = !filterState.onlyChanged;
      if (which === "poor") filterState.onlyPoor = !filterState.onlyPoor;
      const on = btn.classList.toggle("is-on");
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      renderTree(body);
      return;
    }
    const caret = btn.closest(".disc-caret");
    if (caret) {
      // The leading caret is the expand control now — toggle the branch (and stop
      // the whole-row open handler below from also firing).
      e.preventDefault();
      const details = caret.closest("details.disc-branch") as HTMLDetailsElement | null;
      if (details) details.open = !details.open;
      return;
    }
    const sw = btn.closest(".disc-switch") as HTMLButtonElement | null;
    if (sw) {
      // Auto-expand opt-in switch (a click can land on the knob span): flip it in
      // the brain. preventDefault stops the enclosing <summary> from toggling.
      e.preventDefault();
      const id = sw.getAttribute("data-id");
      const on = sw.getAttribute("data-on") === "1";
      if (id) void toggleAutoExpand(sw, id, !on);
      return;
    }
    if (btn.classList.contains("disc-resync")) {
      // Bulk re-pull: ingest is wipe-replace keyed on the page id, so re-posting
      // each stale page's URL syncs it in place — same write path as a pull.
      const urls = currentPages.filter(isStale).map((p) => p.url!);
      if (urls.length) void pullBatch(body, btn as HTMLButtonElement, urls);
      return;
    }
    if (btn.classList.contains("disc-pull-db")) {
      // Pull every not-yet-ingested row of a database in one batch. A pull-all
      // button sits inside the database's <summary>; without this the click
      // would also toggle the branch.
      e.preventDefault();
      const node = nodeById.get(btn.getAttribute("data-id") ?? "");
      const urls = node ? collectChildPages(node).map((p) => p.url!) : [];
      if (urls.length) void pullBatch(body, btn as HTMLButtonElement, urls);
      return;
    }
    if (btn.classList.contains("disc-remove-db")) {
      // Un-ingest every ingested row of a database in one batch — the inverse of
      // pull-all. The button sits inside the database's <summary>, so stop the
      // click from also toggling the branch.
      e.preventDefault();
      const node = nodeById.get(btn.getAttribute("data-id") ?? "");
      const pages = node ? collectIngestedChildPages(node) : [];
      if (pages.length) void removeBatch(body, btn as HTMLButtonElement, pages);
      return;
    }
    if (btn.classList.contains("disc-remove")) {
      // Un-ingest: drop this one page from the brain. Per-page only — no cascade
      // to children. A remove button can sit inside a <summary>; stop the click
      // from also toggling the branch.
      e.preventDefault();
      const id = btn.getAttribute("data-id");
      if (id) void removePage(btn as HTMLButtonElement, id, btn.getAttribute("data-url") ?? "");
      return;
    }
    if (!btn.classList.contains("disc-pull")) {
      // Anywhere else on a row: the whole row opens the page in Notion (this
      // replaced the old hover arrow). preventDefault stops a branch <summary>
      // from also toggling; a row with no url (a database) toggles its branch.
      const row = btn.closest(".disc-row");
      if (row) {
        e.preventDefault();
        const rowUrl = row.getAttribute("data-url");
        if (rowUrl) {
          window.open(rowUrl, "_blank", "noopener");
        } else {
          const details = row.closest("details.disc-branch") as HTMLDetailsElement | null;
          if (details) details.open = !details.open;
        }
      }
      return;
    }
    // A pull button can sit inside a <summary>; without this the click ALSO
    // toggles the branch open/closed.
    e.preventDefault();
    const url = btn.getAttribute("data-url");
    if (!url) return;
    // A page with pullable descendants gets a choice; a leaf pulls directly.
    const node = nodeById.get(btn.getAttribute("data-id") ?? "");
    const kids = node ? collectChildPages(node) : [];
    if (kids.length === 0) {
      void pullPage(btn as HTMLButtonElement, url);
      return;
    }
    showPullModal(body, btn as HTMLButtonElement, node!, kids);
  });
}

// Pullable descendants of a page: walk the subtree, skipping database branches
// entirely (their rows are property-shaped, not documents — pull those
// individually) and skipping pages already in the brain.
function collectChildPages(node: PageNode): NotionPage[] {
  const out: NotionPage[] = [];
  const walk = (n: PageNode) => {
    for (const c of n.children) {
      if (c.page.kind === "database") continue;
      if (!c.page.ingested && c.page.url) out.push(c.page);
      walk(c);
    }
  };
  walk(node);
  return out;
}

// The inverse of collectChildPages — ingested descendants, for bulk removal.
// Same subtree walk and same database-branch skip; removal is keyed on the page
// id (the /api/sources/{id} DELETE), so a row needs an id, not a url.
function collectIngestedChildPages(node: PageNode): NotionPage[] {
  const out: NotionPage[] = [];
  const walk = (n: PageNode) => {
    for (const c of n.children) {
      if (c.page.kind === "database") continue;
      if (c.page.ingested && c.page.id) out.push(c.page);
      walk(c);
    }
  };
  walk(node);
  return out;
}

// --- pull-with-children modal -------------------------------------------------

function showPullModal(
  body: HTMLElement,
  btn: HTMLButtonElement,
  node: PageNode,
  kids: NotionPage[],
): void {
  const title = node.page.title || "(untitled)";
  const n = kids.length;

  // The title is the one untrusted string here; everything else is static.
  const text = document.createElement("div");
  text.innerHTML = `<strong>${esc(title)}</strong> has ${n} child page${
    n === 1 ? "" : "s"
  } not yet in the brain. Pull them too?`;

  const handle = modal({
    title: "Pull options",
    body: text,
    actions: [
      button({
        label: "Just this page",
        onClick: () => {
          handle.close();
          void pullPage(btn, node.page.url ?? "");
        },
      }),
      button({
        label: `Page + ${n} child${n === 1 ? "" : "ren"}`,
        variant: "primary",
        onClick: () => {
          handle.close();
          const urls = [node.page.url, ...kids.map((k) => k.url)].filter(Boolean) as string[];
          void pullBatch(body, btn, urls);
        },
      }),
    ],
  });
  // A fresh modal is built per click (its content is page-specific), so drop it
  // from the DOM once it finishes fading out — no matter which close path ran
  // (×, ESC, scrim, or an action) — so repeated opens don't pile up hidden
  // scrims. close() always clears tk-open, which drives the opacity transition.
  handle.el.classList.add("disc-pull-modal");
  handle.el.addEventListener("transitionend", (e) => {
    if (e.target === handle.el && e.propertyName === "opacity" && !handle.el.classList.contains("tk-open"))
      handle.el.remove();
  });
  handle.open();
}

// Sequential batch pull: ingest each page in turn (the brain embeds per page —
// parallel posts would just queue there anyway), narrating progress on the
// button, then re-render the whole tree from the server so every affected row
// flips to "in brain" at once.
async function pullBatch(body: HTMLElement, btn: HTMLButtonElement, urls: string[]): Promise<void> {
  btn.disabled = true;
  let failed = 0;
  for (let i = 0; i < urls.length; i++) {
    btn.textContent = `pulling ${i + 1}/${urls.length}…`;
    try {
      const res = await fetch(`/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urls[i] }),
      });
      if (!res.ok) failed++;
    } catch {
      failed++;
    }
  }
  await loadPages(body);
  if (failed > 0) toast(`${failed} of ${urls.length} pulls failed — retry from the tree.`);
}

// Sequential batch remove — the inverse of pullBatch: DELETE each source in
// turn, narrating progress on the button, then re-render the whole tree from the
// server so every removed row flips back to a "pull" action at once.
async function removeBatch(
  body: HTMLElement,
  btn: HTMLButtonElement,
  pages: NotionPage[],
): Promise<void> {
  btn.disabled = true;
  let failed = 0;
  for (let i = 0; i < pages.length; i++) {
    btn.textContent = `removing ${i + 1}/${pages.length}…`;
    try {
      const res = await fetch(`/api/sources/${pages[i].id}`, { method: "DELETE" });
      if (!res.ok) failed++;
    } catch {
      failed++;
    }
  }
  await loadPages(body);
  if (failed > 0) toast(`${failed} of ${pages.length} removals failed — retry from the tree.`);
}

// Flip one row between the ingested and not-ingested states in place — no full
// reload, so expanded branches and scroll stay put. Rewrites the three cells
// that differ so the row matches exactly what rowHTML() would render fresh:
//   status → "in brain" badge  |  pull button
//   remove → remove button     |  (empty)
//   health → legibility slot   |  (empty)
// This is the fix for the old replaceWith-the-clicked-button approach, which
// left the remove button missing after a pull (and mis-columned it after a
// remove→re-add, since the pull button had been swapped into the remove cell).
function setRowIngested(row: Element, ingested: boolean, id: string, url: string): void {
  const eid = esc(id);
  const eurl = esc(url);
  const status = row.querySelector<HTMLElement>(".disc-cell-status");
  const remove = row.querySelector<HTMLElement>(".disc-cell-remove");
  const health = row.querySelector<HTMLElement>(".disc-cell-health");
  if (status)
    status.innerHTML = ingested
      ? `<span class="disc-badge is-ingested">in brain</span>`
      : `<button class="disc-pull" type="button" data-id="${eid}" data-url="${eurl}">pull</button>`;
  if (remove)
    remove.innerHTML = ingested
      ? `<button class="disc-remove" type="button" data-id="${eid}" data-url="${eurl}" title="remove from the brain">remove</button>`
      : "";
  if (health) {
    if (ingested) {
      health.setAttribute("data-health-for", eid);
      health.innerHTML = healthBadge(id, healthById.get(id) ?? null);
    } else {
      health.removeAttribute("data-health-for");
      health.innerHTML = "";
    }
  }
}

// Un-ingest one page: DELETE its source from the brain, then flip the row back to
// its not-ingested state in place (and patch the cache, so the next render
// doesn't resurrect the badge). The inverse of pullPage.
async function removePage(btn: HTMLButtonElement, id: string, url: string): Promise<void> {
  btn.disabled = true;
  btn.textContent = "removing…";
  const row = btn.closest(".disc-row");
  try {
    const res = await fetch(`/api/sources/${id}`, { method: "DELETE" });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "retry";
      btn.title = data.error ?? `HTTP ${res.status}`;
      return;
    }
    const cached = currentPages.find((p) => p.id === id);
    if (cached) {
      cached.ingested = false;
      cached.ingested_last_edited = null;
      writeCache(currentPages, fetchedAt);
    }
    if (row) setRowIngested(row, false, id, url);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "retry";
    btn.title = String(err);
  }
}

// Flip a page/database's auto-expand opt-in in the brain, then reflect it on the
// pill in place (and patch the cache so a re-render keeps the state). Opt-in,
// default off — when on, the sync loop auto-pulls new descendants under it.
async function toggleAutoExpand(btn: HTMLButtonElement, id: string, value: boolean): Promise<void> {
  btn.disabled = true;
  try {
    const res = await fetch(`/api/sources/${id}/auto-expand`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_expand: value }),
    });
    btn.disabled = false;
    if (!res.ok) {
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      btn.title = data.error ?? `HTTP ${res.status}`;
      return;
    }
    btn.classList.toggle("is-on", value);
    btn.setAttribute("aria-checked", value ? "true" : "false");
    btn.setAttribute("data-on", value ? "1" : "0");
    const cached = currentPages.find((p) => p.id === id);
    if (cached) {
      cached.auto_expand = value;
      writeCache(currentPages, fetchedAt);
    }
  } catch (err) {
    btn.disabled = false;
    btn.title = String(err);
  }
}

async function pullPage(btn: HTMLButtonElement, url: string): Promise<void> {
  const id = btn.getAttribute("data-id") ?? "";
  btn.disabled = true;
  btn.textContent = "pulling…";
  const row = btn.closest(".disc-row");
  try {
    const res = await fetch(`/api/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "retry";
      btn.title = data.error ?? `HTTP ${res.status}`;
      return;
    }
    // Flip the row to its ingested state in place — no full reload needed — and
    // patch the cache so the next render doesn't resurrect the pull button. The
    // brain just captured the page at its listed edit time; record that too, or
    // the next render would count the fresh pull as stale.
    const cached = currentPages.find((p) => p.url === url);
    if (cached) {
      cached.ingested = true;
      cached.ingested_last_edited = cached.last_edited_time ?? null;
      writeCache(currentPages, fetchedAt);
    }
    if (row) setRowIngested(row, true, cached?.id ?? id, url);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "retry";
    btn.title = String(err);
  }
}
