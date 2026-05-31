import { mountDocs } from "./docs";
import { mountLearnings } from "./learnings";

const captureView = document.getElementById("capture-view") as HTMLElement;
const docsView = document.getElementById("docs-view") as HTMLDivElement;
const learningsView = document.getElementById("learnings-view") as HTMLDivElement;

// Free-text capture is disabled with the document-substrate cutover: the brain's
// write path is now source ingest (Notion pages / docs), not a /capture endpoint.
// The send button is disabled in the markup and there is no POST here — so the UI
// has no broken request and no console error. The capture screen stays as the
// landing view (with a note) until a source-editing surface lands; the docs and
// evolution views below are unaffected.

// Hash router: `#docs` (and `#docs/<section>`) shows the documentation view,
// `#learnings` shows the evolution timeline; anything else is the capture
// screen. Each overlay's HTML is mounted lazily on first visit so it never
// costs the capture path anything.
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
  captureView.hidden = onDocs || onLearnings;
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
