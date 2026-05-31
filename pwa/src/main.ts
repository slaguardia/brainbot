import { mountDocs } from "./docs";
import { mountLearnings } from "./learnings";

const textarea = document.getElementById("capture") as HTMLTextAreaElement;
const sendBtn = document.getElementById("send") as HTMLButtonElement;
const toast = document.getElementById("toast") as HTMLDivElement;
const captureView = document.getElementById("capture-view") as HTMLElement;
const docsView = document.getElementById("docs-view") as HTMLDivElement;
const learningsView = document.getElementById("learnings-view") as HTMLDivElement;

let toastTimer: number | undefined;

function syncSendEnabled() {
  sendBtn.disabled = textarea.value.trim().length === 0;
}
syncSendEnabled();
textarea.addEventListener("input", syncSendEnabled);

function showToast(message: string, kind: "ok" | "error" = "ok") {
  toast.textContent = message;
  toast.classList.toggle("error", kind === "error");
  toast.classList.add("show");
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("show"), 1800);
}

function send() {
  const text = textarea.value.trim();
  if (!text) return;

  // Optimistic: clear UI and ack before the network round-trip. The
  // brain accepts the write quickly but extraction takes 1–3s; we are
  // not waiting on either here.
  textarea.value = "";
  textarea.focus();
  syncSendEnabled();
  showToast("captured");

  void fetch("/api/capture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    })
    .catch(() => {
      // Restore the text so the user can retry. Don't auto-resend —
      // they may have typed more in the meantime.
      textarea.value = textarea.value ? `${text}\n\n${textarea.value}` : text;
      syncSendEnabled();
      showToast("send failed — retry", "error");
    });
}

sendBtn.addEventListener("click", send);

textarea.addEventListener("keydown", (e) => {
  // Cmd/Ctrl+Enter sends. Plain Enter inserts a newline (normal textarea behavior).
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    send();
  }
});

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
  if (onDocs || onLearnings) {
    // Land at the top for a plain entry, but let a `#docs/<section>` deep link
    // keep the scroll position docs.ts set on mount.
    if (!/^#(docs|learnings)\//.test(location.hash)) window.scrollTo(0, 0);
  } else {
    textarea.focus();
  }
}
window.addEventListener("hashchange", route);
route();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      // SW failure is non-fatal — capture still works.
    });
  });
}
