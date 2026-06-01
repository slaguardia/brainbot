import { mountDocs } from "./docs";
import { mountHome } from "./home";

const homeView = document.getElementById("home-view") as HTMLElement;
const homeBody = document.getElementById("home-body") as HTMLElement;
const docsView = document.getElementById("docs-view") as HTMLDivElement;

// The landing view is the home hub: stat tiles + an embedded recall search box +
// a hierarchical source map, all reading the brain through /api/*. (Search and
// the source map used to be separate `#search` / `#map` routes; they live here
// now.) Mounted once on load.
mountHome(homeBody);

// Hash router: `#docs` (and `#docs/<page>`) shows the documentation view — a
// knowledge base whose own sidenav switches between pages (How the brain works,
// Evolution). `#learnings` (and `#learnings/ch<n>`) alias onto the docs view's
// Evolution page so old links resolve. Anything else is the home hub. The docs
// view is mounted lazily on first visit so it never costs the home path
// anything; docs.ts handles page switching on later hash changes.
let docsMounted = false;
function route() {
  const hash = location.hash.replace(/^#/, "");
  const onDocs = hash.startsWith("docs") || hash.startsWith("learnings");
  if (onDocs && !docsMounted) {
    mountDocs(docsView);
    docsMounted = true;
  }
  docsView.hidden = !onDocs;
  homeView.hidden = onDocs;
  if (onDocs && !/^#(docs|learnings)\//.test(location.hash)) {
    // Land at the top for a plain entry, but let a `#docs/<page>/<section>` deep
    // link keep the scroll position docs.ts set on mount.
    window.scrollTo(0, 0);
  }
}
window.addEventListener("hashchange", route);
route();

// Service worker: register it only for the installed PWA (production). On
// localhost the app-shell cache just masks fresh dev builds, so instead tear
// down any SW + caches a previous visit left behind (self-healing dev).
const onLocalhost = ["localhost", "127.0.0.1", "[::1]", ""].includes(location.hostname);
if ("serviceWorker" in navigator) {
  if (onLocalhost) {
    void navigator.serviceWorker.getRegistrations().then((regs) => {
      for (const r of regs) void r.unregister();
    });
    if (window.caches) {
      void caches.keys().then((keys) => {
        for (const k of keys) void caches.delete(k);
      });
    }
  } else {
    window.addEventListener("load", () => {
      void navigator.serviceWorker.register("/sw.js").catch(() => {
        // SW failure is non-fatal — the docs/evolution views still work offline.
      });
    });
  }
}
