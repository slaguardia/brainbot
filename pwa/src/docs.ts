// The documentation view — a knowledge base with a left sidenav. The sidenav
// carries the brain wordmark on top and a tab per PAGE ("How the brain works",
// "Evolution"); the center column holds the active page's article; the right
// rail is the in-page "on this page" tracker (scrollspy).
//
// Page content is RENDERED FROM THE CANONICAL REPO DOCS at build time — the
// markdown files are bundled via Vite `?raw` imports and parsed with marked on
// first mount. There is no hand-mirrored copy to keep in sync: edit
// docs/brain-architecture.md or docs/learnings.md and this view follows on the
// next build. Sections split at `##` headings (a "Chapter N — …" heading keeps
// the legacy `ch<n>` anchor so old `#learnings/ch<n>` deep links resolve).
// innerHTML is safe — the markdown is our own repo content, no user input.
// Reached via `#docs` (and `#docs/<page>`); `#learnings` (and
// `#learnings/ch<n>`) alias onto the Evolution page.

import { marked, type Token, type TokensList } from "marked";

import brainArchitectureMd from "../../docs/brain-architecture.md?raw";
import learningsMd from "../../docs/learnings.md?raw";

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

// Markdown-to-page rendering -----------------------------------------------

// Cross-doc links only make sense in the repo. Links to a doc that has an
// in-app page are rewritten onto its route; links to any other relative .md
// file degrade to their label text (absolute http(s) links pass through).
const MD_PAGE_ROUTES: Record<string, string> = {
  "brain-architecture.md": "#docs/how-it-works",
  "learnings.md": "#docs/evolution",
};

function rewriteRelativeMdLinks(md: string): string {
  return md.replace(
    /\[([^\]]+)\]\((\.{1,2}\/[^)\s]*?\.md)(#[^)]*)?\)/g,
    (_m, label: string, path: string) => {
      const route = MD_PAGE_ROUTES[path.split("/").pop() ?? ""];
      return route ? `[${label}](${route})` : label;
    },
  );
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Section id: legacy `ch<n>` for "Chapter N — …" headings (keeps old deep
// links resolving), slugified heading text otherwise.
function sectionId(heading: string): string {
  const chapter = /^Chapter (\d+)\b/.exec(heading);
  if (chapter) return `ch${chapter[1]}`;
  return heading
    .toLowerCase()
    .replace(/`/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Rail label: heading text minus inline-code backticks and any trailing
// parenthetical (the rail column is narrow).
function sectionLabel(heading: string): string {
  return heading.replace(/`/g, "").replace(/\s*\([^)]*\)\s*$/, "");
}

function parseGroup(tokens: Token[]): string {
  const list = tokens as TokensList;
  list.links = {};
  return marked.parser(list);
}

// Split a markdown doc into the page shape: the `#` title + everything before
// the first `##` becomes the hero; each `##` heading starts a docs-section
// (the section wrapper carries the scrollspy id).
function buildPage(id: string, label: string, md: string): DocPage {
  const tokens = marked.lexer(rewriteRelativeMdLinks(md));
  let title = label;
  const intro: Token[] = [];
  const groups: { heading: string; tokens: Token[] }[] = [];
  for (const t of tokens) {
    if (t.type === "heading" && t.depth === 1) {
      title = t.text;
      continue;
    }
    if (t.type === "heading" && t.depth === 2) {
      groups.push({ heading: t.text, tokens: [t] });
      continue;
    }
    (groups.length ? groups[groups.length - 1].tokens : intro).push(t);
  }

  const sections = groups.map((g) => ({
    id: sectionId(g.heading),
    label: sectionLabel(g.heading),
  }));
  const body =
    `<header class="docs-hero"><h1>${escapeHtml(title)}</h1>` +
    `<div class="docs-lead">${parseGroup(intro)}</div></header>` +
    groups
      .map(
        (g, i) =>
          `<section class="docs-section" id="${sections[i].id}">${parseGroup(g.tokens)}</section>`,
      )
      .join("");
  return { id, label, sections, body };
}

const PAGES: DocPage[] = [
  buildPage("how-it-works", "How the brain works", brainArchitectureMd),
  buildPage("evolution", "Evolution", learningsMd),
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
