// The discovery view (`#discover`) — what the Notion integration can see vs.
// what's in the brain. GET /api/notion/pages returns every shared page (children
// included) as flat {id, title, parent_id, last_edited_time, url, ingested}
// facts; this view builds the parent/child tree and offers a per-page "pull"
// action that POSTs the page's URL to /api/ingest (the brain's existing write
// path). Selective pull only — no resync/staleness management lives here.
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

interface NotionPage {
  id?: string;
  kind?: string; // 'page' | 'database' — database rows are pages parented by a database
  title?: string;
  parent_id?: string | null;
  last_edited_time?: string | null;
  url?: string;
  ingested?: boolean;
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
  void loadPages(body);
}

async function loadPages(body: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/notion/pages`);
    const data = (await res.json()) as { pages?: NotionPage[]; error?: string };
    if (!res.ok) {
      body.innerHTML = `<p class="home-status">Discovery failed: ${esc(data.error ?? `HTTP ${res.status}`)}</p>`;
      return;
    }
    renderPages(body, Array.isArray(data.pages) ? data.pages : []);
  } catch (err) {
    body.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(err)}).</p>`;
  }
}

// --- parent/child tree -------------------------------------------------------

interface PageNode {
  page: NotionPage;
  children: PageNode[];
}

// Roots = pages whose parent isn't itself a visible page (workspace/database/
// block parents, or a parent page that wasn't shared with the integration).
function buildTree(pages: NotionPage[]): PageNode[] {
  const nodes = new Map<string, PageNode>();
  for (const p of pages) {
    if (p.id) nodes.set(p.id, { page: p, children: [] });
  }
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
  body.innerHTML = `
    <p class="disc-counts">${n} page${n === 1 ? "" : "s"} visible · ${nIn} in the brain</p>
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
      : `<button class="disc-pull" type="button" data-url="${esc(p.url ?? "")}">pull</button>`;
  return `
      ${isDb ? `<span class="disc-kind-db">db</span>` : ""}
      <span class="src-label ${isDb ? "is-db" : ""}">${title}</span>
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
    if (!btn.classList.contains("disc-pull")) return;
    // A pull button can sit inside a <summary>; without this the click ALSO
    // toggles the branch open/closed.
    e.preventDefault();
    const url = btn.getAttribute("data-url");
    if (!url) return;
    void pullPage(btn as HTMLButtonElement, url);
  });
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
    // Swap the button for the ingested badge in place — no full reload needed.
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
