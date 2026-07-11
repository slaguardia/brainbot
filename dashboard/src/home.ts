// The landing view (default route, no hash) — the one place you *read* the
// brain. Deliberately spare: a single hybrid-recall search box over every
// ingested source, and a button through to the Notion pages view (#discover),
// which is where you *browse and manage* what's in the brain.
//
// The source map + Notion sync status that used to share this screen now live on
// #discover (they were a second copy of that view's tree). Search stays here so
// reading and managing are two clean, separate surfaces instead of one crowded
// hub.
//
// recall() calls the owner read-proxy (/api/brain/recall) in server/index.ts.
// All brain-returned strings (headings, recall text, paths) are escaped before
// they touch innerHTML — source data is never markup.

import { recall, type Chunk } from "@brainbot/web-toolkit/brain";

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

type RecallChunk = Pick<Chunk, "heading" | "text" | "score" | "path">;

export function mountHome(container: HTMLElement): void {
  // The shared header/nav chrome is rendered by the toolkit shell (mountApp);
  // this view renders only its body into the content region. No brain read on
  // load — the search box is inert until you submit, so the landing paints
  // instantly and never depends on the brain being reachable to appear.
  container.innerHTML = `
    <section class="home landing">
      <header class="page-head">
        <h1 class="page-title">Your brain</h1>
        <p class="page-sub">
          Search everything the brain has ingested — or browse and manage your
          Notion pages.
        </p>
      </header>

      <form class="home-search" id="home-search-form" role="search">
        <input id="home-q" class="tk-input" type="search" placeholder="Search the brain…" autocomplete="off" />
        <button type="submit">Recall</button>
      </form>

      <div class="home-results" hidden></div>

      <a class="home-browse" href="#discover">Browse Notion pages →</a>
    </section>`;

  wireSearch(container);
}

// --- Embedded recall search ------------------------------------------------

function wireSearch(container: HTMLElement): void {
  const form = container.querySelector<HTMLFormElement>("#home-search-form");
  const input = container.querySelector<HTMLInputElement>("#home-q");
  const results = container.querySelector<HTMLDivElement>(".home-results");
  const browse = container.querySelector<HTMLElement>(".home-browse");
  const button = container.querySelector<HTMLButtonElement>("#home-search-form button");
  if (!form || !input || !results || !browse || !button) return;

  const showLanding = () => {
    results.hidden = true;
    results.innerHTML = "";
    browse.hidden = false;
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) {
      showLanding();
      return;
    }
    // While results are up the browse button steps aside, so the answer is the
    // whole screen; clearing brings it back.
    browse.hidden = true;
    results.hidden = false;
    results.innerHTML = `<p class="home-status">Searching…</p>`;
    button.disabled = true;
    void runRecall(q, results).finally(() => {
      button.disabled = false;
    });
  });

  // Delegated "clear" — restore the bare landing.
  results.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t.classList.contains("home-clear")) {
      e.preventDefault();
      input.value = "";
      showLanding();
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
