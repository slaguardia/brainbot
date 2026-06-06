// The discovery view (`#discover`) — what the Notion integration can see vs.
// what's in the brain. GET /api/notion/pages returns every shared page (children
// included) as flat {id, title, parent_id, last_edited_time, url, ingested,
// ingested_last_edited} facts; this view builds the parent/child tree and offers
// a per-page "pull" action that POSTs the page's URL to /api/ingest (the brain's
// existing write path), plus ONE bulk "re-pull" button for ingested pages whose
// Notion copy moved past what the brain captured. No per-page resync UI.
//
// All Notion-returned strings (titles) are escaped before they touch innerHTML.

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export interface NotionPage {
  id?: string;
  kind?: string; // 'page' | 'database' — database rows are pages parented by a database
  title?: string;
  parent_id?: string | null;
  last_edited_time?: string | null;
  url?: string;
  ingested?: boolean;
  ingested_last_edited?: string | null; // origin edit time the brain captured at ingest
}

// A pulled page is stale when Notion's copy moved past the one the brain
// captured at ingest — or when the brain recorded no edit time at all (sources
// ingested before that was stored), where "possibly stale" must mean re-pull.
// Exported: the home dashboard's sync status applies the same rule.
export function isStale(p: NotionPage): boolean {
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

// The page list for callers outside this view (the home dashboard's sync
// status): cached copy when one exists, live sweep otherwise — and a live
// sweep always refreshes the shared cache, so the two views agree.
export async function fetchNotionPages(force = false): Promise<NotionPage[]> {
  if (!force) {
    const cached = readCache();
    if (cached) {
      currentPages = cached;
      return cached;
    }
  }
  const res = await fetch(`/api/notion/pages`);
  const data = (await res.json()) as { pages?: NotionPage[]; error?: string };
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  const pages = Array.isArray(data.pages) ? data.pages : [];
  currentPages = pages;
  writeCache(pages);
  return pages;
}

export function mountDiscover(container: HTMLElement): void {
  container.innerHTML = `
    <header class="cap-head">
      <a class="brand" href="#" aria-label="brain — back to home">brain</a>
      <nav class="cap-nav" aria-label="Brain views">
        <a href="#docs">docs</a>
      </nav>
    </header>
    <section class="home discover">
      <div class="disc-head">
        <h2>Notion pages</h2>
        <a class="disc-refresh" href="#discover">Refresh</a>
      </div>
      <p class="disc-sub">
        Every page shared with the integration. Pull the ones you want into the brain.
      </p>
      <div class="disc-body"><p class="home-status">Asking Notion…</p></div>
    </section>`;
  const body = container.querySelector<HTMLElement>(".disc-body")!;
  container.querySelector<HTMLAnchorElement>(".disc-refresh")!.addEventListener("click", (e) => {
    e.preventDefault();
    body.innerHTML = `<p class="home-status">Asking Notion…</p>`;
    void loadPages(body);
  });
  // Delegated pull handler, attached ONCE — renders replace body.innerHTML, so a
  // per-render listener would stack across refreshes and double-fire ingest.
  wireIngest(body);
  const cached = readCache();
  if (cached) {
    currentPages = cached;
    renderPages(body, cached);
  } else {
    void loadPages(body);
  }
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

// --- parent/child tree -------------------------------------------------------

interface PageNode {
  page: NotionPage;
  children: PageNode[];
}

// The last-rendered tree, by page id — lets the pull handler find a clicked
// page's children for the pull-with-children modal.
let nodeById = new Map<string, PageNode>();

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
  const roots = buildTree(pages);
  const real = pages.filter((p) => p.kind !== "database");
  const n = real.length;
  const nIn = real.filter((p) => p.ingested).length;
  const at = fetchedAt
    ? ` · synced ${new Date(fetchedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : "";
  // One bulk action — re-pull every ingested page whose Notion copy moved.
  // No per-page resync UI; the handler recomputes the stale set from
  // currentPages on click.
  const nStale = real.filter(isStale).length;
  const resync = nStale
    ? ` · <button class="disc-resync" type="button">re-pull ${nStale} changed</button>`
    : "";
  body.innerHTML = `
    <p class="disc-counts">${n} page${n === 1 ? "" : "s"} visible · ${nIn} in the brain${at}${resync}</p>
    <ul class="src-list disc-tree">${roots.map(renderNode).join("")}</ul>`;
}

// One row: title grows, edited date + action hug the right. Databases aren't
// pullable (ingest is page-only) — they show a row count instead.
function rowHTML(node: PageNode): string {
  const p = node.page;
  const isDb = p.kind === "database";
  const title = esc(p.title || "(untitled)");
  const edited = !isDb && p.last_edited_time ? esc(p.last_edited_time.slice(0, 10)) : "";
  const action = isDb
    ? `<span class="disc-count">${node.children.length} page${node.children.length === 1 ? "" : "s"}</span>`
    : p.ingested
      ? `<span class="disc-badge is-ingested">in brain</span>`
      : `<button class="disc-pull" type="button" data-id="${esc(p.id ?? "")}" data-url="${esc(p.url ?? "")}">pull</button>`;
  return `
      ${isDb ? `<span class="disc-kind-db">db</span>` : ""}
      <span class="src-label">${title}</span>
      ${edited ? `<span class="disc-edited">${edited}</span>` : ""}
      ${action}`;
}

function renderNode(node: PageNode): string {
  // A parent (page with sub-pages, or a database with rows) renders as a native
  // <details> so it collapses; collapsed by default keeps big databases (every
  // row is a page) from flooding the view. Leaves stay plain rows.
  if (node.children.length) {
    return `
    <li class="src-node is-source">
      <details class="disc-branch">
        <summary class="disc-row">${rowHTML(node)}</summary>
        <ul class="src-list">${node.children.map(renderNode).join("")}</ul>
      </details>
    </li>`;
  }
  return `
    <li class="src-node is-source">
      <span class="disc-row">${rowHTML(node)}</span>
    </li>`;
}

// --- selective pull ----------------------------------------------------------

function wireIngest(body: HTMLElement): void {
  body.addEventListener("click", (e) => {
    const btn = e.target as HTMLElement;
    if (btn.classList.contains("disc-resync")) {
      // Bulk re-pull: ingest is wipe-replace keyed on the page id, so re-posting
      // each stale page's URL syncs it in place — same write path as a pull.
      const urls = currentPages.filter(isStale).map((p) => p.url!);
      if (urls.length) void pullBatch(body, btn as HTMLButtonElement, urls);
      return;
    }
    if (!btn.classList.contains("disc-pull")) return;
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

// --- pull-with-children modal -------------------------------------------------

function showPullModal(
  body: HTMLElement,
  btn: HTMLButtonElement,
  node: PageNode,
  kids: NotionPage[],
): void {
  const title = node.page.title || "(untitled)";
  const n = kids.length;
  const overlay = document.createElement("div");
  overlay.className = "disc-modal-overlay";
  overlay.innerHTML = `
    <div class="disc-modal" role="dialog" aria-modal="true" aria-label="Pull options">
      <p class="disc-modal-text">
        <strong>${esc(title)}</strong> has ${n} child page${n === 1 ? "" : "s"} not yet
        in the brain. Pull them too?
      </p>
      <div class="disc-modal-actions">
        <button type="button" class="disc-pull" data-act="one">Just this page</button>
        <button type="button" class="disc-pull" data-act="all">Page + ${n} child${n === 1 ? "" : "ren"}</button>
        <button type="button" class="disc-modal-cancel" data-act="cancel">Cancel</button>
      </div>
    </div>`;
  overlay.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    const act = t === overlay ? "cancel" : t.getAttribute("data-act");
    if (!act) return;
    overlay.remove();
    if (act === "one") void pullPage(btn, node.page.url ?? "");
    if (act === "all") {
      const urls = [node.page.url, ...kids.map((k) => k.url)].filter(Boolean) as string[];
      void pullBatch(body, btn, urls);
    }
  });
  document.body.appendChild(overlay);
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
  if (failed > 0) {
    body.insertAdjacentHTML(
      "afterbegin",
      `<p class="home-status">${failed} of ${urls.length} pulls failed — retry from the tree.</p>`,
    );
  }
}

async function pullPage(btn: HTMLButtonElement, url: string): Promise<void> {
  btn.disabled = true;
  btn.textContent = "pulling…";
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
    // Swap the button for the ingested badge in place — no full reload needed —
    // and patch the cache so the next render doesn't resurrect the pull button.
    // The brain just captured the page at its listed edit time; record that too,
    // or the next render would count the fresh pull as stale.
    const cached = currentPages.find((p) => p.url === url);
    if (cached) {
      cached.ingested = true;
      cached.ingested_last_edited = cached.last_edited_time ?? null;
      writeCache(currentPages, fetchedAt);
    }
    const badge = document.createElement("span");
    badge.className = "disc-badge is-ingested";
    badge.textContent = "in brain";
    btn.replaceWith(badge);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "retry";
    btn.title = String(err);
  }
}
