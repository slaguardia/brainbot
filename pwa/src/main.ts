import { mountDocs } from "./docs";
import { mountHome } from "./home";
import { mountLearnings } from "./learnings";
import { mountSearch, mountMap } from "./views";

const homeView = document.getElementById("home-view") as HTMLElement;
const homeBody = document.getElementById("home-body") as HTMLElement;
const docsView = document.getElementById("docs-view") as HTMLDivElement;
const learningsView = document.getElementById("learnings-view") as HTMLDivElement;
const searchView = document.getElementById("search-view") as HTMLDivElement;
const mapView = document.getElementById("map-view") as HTMLDivElement;

// Free-text capture is disabled with the document-substrate cutover: the brain's
// write path is now source ingest (Notion pages / docs), not a /capture endpoint.
// So the landing view is a small dashboard of high-level facts about the brain
// (source + domain counts, read from /api/map) rather than a capture box; the
// docs and evolution views below are unaffected.
mountHome(homeBody);

// Hash router: `#docs` (and `#docs/<section>`) shows the documentation view,
// `#learnings` shows the evolution timeline, `#search` the recall search box,
// `#map` the source map; anything else is the home dashboard. Each overlay's
// HTML is mounted lazily on first visit so it never costs the home path
// anything. `#search` / `#map` are owner read-views over the brain.
let docsMounted = false;
let learningsMounted = false;
let searchMounted = false;
let mapMounted = false;
function route() {
  const hash = location.hash.replace(/^#/, "");
  const onDocs = hash.startsWith("docs");
  const onLearnings = hash.startsWith("learnings");
  const onSearch = hash.startsWith("search");
  const onMap = hash.startsWith("map");
  if (onDocs && !docsMounted) {
    mountDocs(docsView);
    docsMounted = true;
  }
  if (onLearnings && !learningsMounted) {
    mountLearnings(learningsView);
    learningsMounted = true;
  }
  if (onSearch && !searchMounted) {
    mountSearch(searchView);
    searchMounted = true;
  }
  if (onMap && !mapMounted) {
    mountMap(mapView);
    mapMounted = true;
  }
  docsView.hidden = !onDocs;
  learningsView.hidden = !onLearnings;
  searchView.hidden = !onSearch;
  mapView.hidden = !onMap;
  homeView.hidden = onDocs || onLearnings || onSearch || onMap;
  if (
    (onDocs || onLearnings || onSearch || onMap) &&
    !/^#(docs|learnings)\//.test(location.hash)
  ) {
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
