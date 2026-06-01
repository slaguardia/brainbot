// The home dashboard (default view, no hash): a few high-level facts about the
// brain — how many sources it holds and how they break down by top-level domain.
// It reads the same owner read-proxy the map view uses (GET /api/map →
// {sources: [{path, title}]}) and derives the counts client-side, so there's no
// new backend surface. Free-text capture is paused (the brain ingests sources,
// not raw text), so this view replaces the old capture textarea as the landing
// screen; a slim note points at the docs for the why.
//
// All brain-returned strings (domain names off source paths) are escaped before
// they land in innerHTML — source data is never markup.

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
      container.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(res.status)}).</p>${CAPTURE_NOTE}`;
      return;
    }
    const data = (await res.json()) as { sources?: MapSource[] };
    const sources = Array.isArray(data.sources) ? data.sources : [];
    container.innerHTML = renderDash(sources);
  } catch (err) {
    container.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(err)}).</p>${CAPTURE_NOTE}`;
  }
}

// Top-level path segment = "domain" (e.g. "Career/Job Search" → "Career"). A
// source with no path is grouped under "Uncategorized".
function domainOf(path: string): string {
  const trimmed = path.trim();
  return trimmed ? trimmed.split("/")[0] : "Uncategorized";
}

function renderDash(sources: MapSource[]): string {
  if (sources.length === 0) {
    return `
      <div class="home-hero">
        <p class="home-lead">The brain is empty — no sources ingested yet.</p>
      </div>
      ${CAPTURE_NOTE}`;
  }

  const counts = new Map<string, number>();
  for (const s of sources) {
    const d = domainOf(s.path ?? "");
    counts.set(d, (counts.get(d) ?? 0) + 1);
  }
  const domains = [...counts.entries()].sort((a, b) => b[1] - a[1]);

  const lead = `${sources.length} source${sources.length === 1 ? "" : "s"} across ${domains.length} domain${domains.length === 1 ? "" : "s"}.`;

  const rows = domains
    .map(
      ([name, n]) => `
      <li class="dom-row">
        <span class="dom-name">${esc(name)}</span>
        <span class="dom-count">${n}</span>
      </li>`,
    )
    .join("");

  return `
    <div class="home-hero">
      <p class="home-lead">${esc(lead)}</p>
    </div>
    <div class="home-stats">
      <div class="stat">
        <span class="stat-num">${sources.length}</span>
        <span class="stat-label">Sources</span>
      </div>
      <div class="stat">
        <span class="stat-num">${domains.length}</span>
        <span class="stat-label">Domains</span>
      </div>
    </div>
    <section class="home-domains">
      <h2>Domains</h2>
      <ul class="dom-list">${rows}</ul>
    </section>
    ${CAPTURE_NOTE}`;
}
