import { mountDocs } from "./docs";
import { mountHome } from "./home";
import { mountLearnings } from "./learnings";

const homeView = document.getElementById("home-view") as HTMLElement;
const homeBody = document.getElementById("home-body") as HTMLElement;
const docsView = document.getElementById("docs-view") as HTMLDivElement;
const learningsView = document.getElementById("learnings-view") as HTMLDivElement;

// The landing view is the home hub: stat tiles + an embedded recall search box +
// a hierarchical source map, all reading the brain through /api/*. (Search and
// the source map used to be separate `#search` / `#map` routes; they live here
// now.) Mounted once on load.
mountHome(homeBody);

// Hash router: `#docs` (and `#docs/<section>`) shows the documentation view,
// `#learnings` shows the evolution timeline; anything else is the home hub. Each
// overlay's HTML is mounted lazily on first visit so it never costs the home
// path anything.
let docsMounted = false;
let learningsMounted = false;
function route() {
  const hash = location.hash.replace(/^#/, "");
  const onDocs = hash.startsWith("docs");
  const onLearnings = hash.startsWith("learnings");
  if (onDocs && !docsMounted) {
    mountDocs(docsView);
    docsMounted = true;
  }
  if (onLearnings && !learningsMounted) {
    mountLearnings(learningsView);
    learningsMounted = true;
  }
  docsView.hidden = !onDocs;
  learningsView.hidden = !onLearnings;
  homeView.hidden = onDocs || onLearnings;
  if ((onDocs || onLearnings) && !/^#(docs|learnings)\//.test(location.hash)) {
    // Land at the top for a plain entry, but let a `#docs/<section>` deep link
    // keep the scroll position docs.ts set on mount.
    window.scrollTo(0, 0);
  }
}
window.addEventListener("hashchange", route);
route();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      // SW failure is non-fatal — the docs/evolution views still work offline.
    });
  });
}
