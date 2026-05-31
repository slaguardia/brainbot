import { mountDocs } from "./docs";
import { mountLearnings } from "./learnings";
import { mountSearch, mountMap } from "./views";

const captureView = document.getElementById("capture-view") as HTMLElement;
const docsView = document.getElementById("docs-view") as HTMLDivElement;
const learningsView = document.getElementById("learnings-view") as HTMLDivElement;
const searchView = document.getElementById("search-view") as HTMLDivElement;
const mapView = document.getElementById("map-view") as HTMLDivElement;

// Free-text capture is disabled with the document-substrate cutover: the brain's
// write path is now source ingest (Notion pages / docs), not a /capture endpoint.
// The send button is disabled in the markup and there is no POST here — so the UI
// has no broken request and no console error. The capture screen stays as the
// landing view (with a note) until a source-editing surface lands; the docs and
// evolution views below are unaffected.

// Hash router: `#docs` (and `#docs/<section>`) shows the documentation view,
// `#learnings` shows the evolution timeline, `#search` the recall search box,
// `#map` the source map; anything else is the capture screen. Each overlay's
// HTML is mounted lazily on first visit so it never costs the capture path
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
  captureView.hidden = onDocs || onLearnings || onSearch || onMap;
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
