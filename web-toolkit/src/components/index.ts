/**
 * components — vanilla factories returning HTMLElement, harvested from scout's
 * internal/web/index.html primitives (button, badge, card, table, modal, the
 * SSE progress drawer). NO third-party component library. Their CSS ships in the
 * toolkit's components.css — an app must
 *   import "@brainbot/web-toolkit/components.css";
 * for these to look right (base.css supplies the tokens they reference).
 */

/* ---- button (scout .btn) ------------------------------------------------- */

export type ButtonVariant = "default" | "primary" | "accent" | "danger";
export type ButtonOptions = {
  label: string;
  variant?: ButtonVariant;
  onClick?: (ev: MouseEvent) => void;
  disabled?: boolean;
};

export function button(opts: ButtonOptions): HTMLButtonElement {
  const el = document.createElement("button");
  el.className = "tk-btn";
  if (opts.variant === "primary") el.classList.add("tk-btn-primary");
  else if (opts.variant === "accent") el.classList.add("tk-btn-accent");
  else if (opts.variant === "danger") el.classList.add("tk-btn-danger");
  el.textContent = opts.label;
  if (opts.disabled) el.disabled = true;
  if (opts.onClick) el.addEventListener("click", opts.onClick);
  return el;
}

/* ---- badge (scout .pill — semantic status chip) -------------------------- */

export type BadgeVariant = "neutral" | "yes" | "maybe" | "no" | "info";

export function badge(label: string, variant: BadgeVariant = "neutral"): HTMLElement {
  const el = document.createElement("span");
  el.className = "tk-badge";
  if (variant !== "neutral") el.classList.add(`tk-badge-${variant}`);
  el.textContent = label;
  return el;
}

/* ---- card (scout's bordered raised surface) ------------------------------ */

export type CardOptions = {
  title?: string;
  /** Body content: a string (text) or an element to append. */
  body?: string | Node;
};

export function card(opts: CardOptions = {}): HTMLElement {
  const el = document.createElement("div");
  el.className = "tk-card";
  if (opts.title) {
    const h = document.createElement("div");
    h.className = "tk-card-title";
    h.textContent = opts.title;
    el.appendChild(h);
  }
  if (opts.body !== undefined) {
    const b = document.createElement("div");
    b.className = "tk-card-body";
    if (typeof opts.body === "string") b.textContent = opts.body;
    else b.appendChild(opts.body);
    el.appendChild(b);
  }
  return el;
}

/* ---- table (scout table + .table-wrap) ----------------------------------- */

export type TableOptions = {
  columns: string[];
  /** Each row is a list of cell contents (string or element), one per column. */
  rows: Array<Array<string | Node>>;
  /** Optional per-row click handler (whole row is clickable, scout-style). */
  onRowClick?: (rowIndex: number) => void;
  /** Make headers click-to-sort (by cell text, numeric-aware). Opt-in. */
  sortable?: boolean;
};

export function table(opts: TableOptions): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "tk-table-wrap";
  const tbl = document.createElement("table");
  tbl.className = "tk-table";

  const thead = document.createElement("thead");
  const htr = document.createElement("tr");
  for (const col of opts.columns) {
    const th = document.createElement("th");
    th.textContent = col;
    htr.appendChild(th);
  }
  thead.appendChild(htr);
  tbl.appendChild(thead);

  const tbody = document.createElement("tbody");
  opts.rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    if (opts.onRowClick) {
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => opts.onRowClick!(i));
    }
    for (const cell of row) {
      const td = document.createElement("td");
      if (typeof cell === "string") td.textContent = cell;
      else td.appendChild(cell);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);

  if (opts.sortable) wireSort(thead, tbody, opts.rows);

  wrap.appendChild(tbl);
  return wrap;
}

/**
 * Wire click-to-sort on a table's headers. Sorts by each cell's text content
 * (numeric-aware), toggling asc/desc, and reflects state via `aria-sort` + a
 * caret on the active header. Reorders the existing <tr> nodes, so any per-row
 * click handler keeps reporting its ORIGINAL index (the caller's data array is
 * untouched).
 */
function wireSort(
  thead: HTMLElement,
  tbody: HTMLElement,
  rows: Array<Array<string | Node>>,
): void {
  const ths = Array.from(thead.querySelectorAll("th"));
  const trs = Array.from(tbody.children); // snapshot in original order
  const keyOf = (cell: string | Node) =>
    (typeof cell === "string" ? cell : (cell.textContent ?? "")).trim();
  let activeCol = -1;
  let dir: 1 | -1 = 1;
  ths.forEach((th, col) => {
    th.classList.add("tk-th-sortable");
    th.addEventListener("click", () => {
      dir = activeCol === col && dir === 1 ? -1 : 1;
      activeCol = col;
      const order = rows
        .map((row, i) => ({ i, key: keyOf(row[col]) }))
        .sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }) * dir);
      for (const { i } of order) tbody.appendChild(trs[i]);
      ths.forEach((h, c) => {
        const on = c === col;
        h.setAttribute("aria-sort", on ? (dir === 1 ? "ascending" : "descending") : "none");
        h.classList.toggle("tk-th-asc", on && dir === 1);
        h.classList.toggle("tk-th-desc", on && dir === -1);
      });
    });
  });
}

/* ---- modal (scout .modal-scrim / .modal) --------------------------------- */

export type ModalHandle = {
  /** The scrim root — append it to the document yourself, or call open(). */
  el: HTMLElement;
  open(): void;
  close(): void;
};

export type ModalOptions = {
  title: string;
  /** Body content: a string or an element. */
  body: string | Node;
  /** Footer action buttons (use `button()`), left-to-right. */
  actions?: HTMLElement[];
  /** Append to document.body and wire ESC/scrim-click to close. Default true. */
  attach?: boolean;
};

export function modal(opts: ModalOptions): ModalHandle {
  const scrim = document.createElement("div");
  scrim.className = "tk-modal-scrim";

  const box = document.createElement("div");
  box.className = "tk-modal";

  const head = document.createElement("div");
  head.className = "tk-modal-head";
  const h2 = document.createElement("h2");
  h2.textContent = opts.title;
  const closeBtn = document.createElement("button");
  closeBtn.className = "tk-modal-close";
  closeBtn.textContent = "close";
  head.appendChild(h2);
  head.appendChild(closeBtn);

  const bodyEl = document.createElement("div");
  bodyEl.className = "tk-modal-body";
  if (typeof opts.body === "string") bodyEl.textContent = opts.body;
  else bodyEl.appendChild(opts.body);

  box.appendChild(head);
  box.appendChild(bodyEl);

  if (opts.actions?.length) {
    const foot = document.createElement("div");
    foot.className = "tk-modal-foot";
    for (const a of opts.actions) foot.appendChild(a);
    box.appendChild(foot);
  }

  scrim.appendChild(box);

  // Announce the overlay as a modal dialog labelled by its title.
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", opts.title);
  box.tabIndex = -1;

  // Track what had focus so close() can restore it — keyboard users land back
  // where they were, not at the top of the document.
  let restoreFocus: HTMLElement | null = null;

  // Declared as hoisted functions so open/close/onKey can reference each other.
  function onKey(e: KeyboardEvent): void {
    if (e.key === "Escape") close();
  }
  function open(): void {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    scrim.classList.add("tk-open");
    // ESC is wired ONLY while open and torn down on close — so a modal never
    // leaks a permanent window listener (and ESC won't close a closed modal).
    document.addEventListener("keydown", onKey);
    box.focus();
  }
  function close(): void {
    scrim.classList.remove("tk-open");
    document.removeEventListener("keydown", onKey);
    restoreFocus?.focus();
  }

  closeBtn.addEventListener("click", close);
  scrim.addEventListener("click", (e) => {
    if (e.target === scrim) close();
  });

  if (opts.attach !== false) document.body.appendChild(scrim);

  return { el: scrim, open, close };
}

/* ---- progress / SSE view (scout .drawer streamJob) ----------------------- */

export type ProgressHandle = {
  el: HTMLElement;
  open(title?: string): void;
  /** Append a log line; `kind` tints it (scout's err/warn gutters). */
  log(text: string, kind?: "info" | "warn" | "error"): void;
  /** Mark the run done: hide the spinner, swap cancel→close. */
  done(): void;
  close(): void;
};

export type ProgressOptions = {
  title?: string;
  /** Called when the user clicks "cancel" during a run. */
  onCancel?: () => void;
  attach?: boolean;
};

export function progress(opts: ProgressOptions = {}): ProgressHandle {
  const el = document.createElement("div");
  el.className = "tk-progress";

  const head = document.createElement("div");
  head.className = "tk-progress-head";
  const spinner = document.createElement("span");
  spinner.className = "tk-spinner";
  const titleEl = document.createElement("span");
  titleEl.className = "tk-progress-title";
  titleEl.textContent = opts.title ?? "run";
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "cancel";
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "close";
  closeBtn.style.display = "none";
  head.append(spinner, titleEl, cancelBtn, closeBtn);

  const logEl = document.createElement("div");
  logEl.className = "tk-progress-log";

  el.append(head, logEl);

  const open = (title?: string) => {
    if (title) titleEl.textContent = title;
    logEl.replaceChildren();
    spinner.style.display = "";
    cancelBtn.style.display = "";
    closeBtn.style.display = "none";
    el.classList.add("tk-open");
  };
  const close = () => el.classList.remove("tk-open");
  const done = () => {
    spinner.style.display = "none";
    cancelBtn.style.display = "none";
    closeBtn.style.display = "";
  };
  const log = (text: string, kind: "info" | "warn" | "error" = "info") => {
    const ln = document.createElement("div");
    ln.className =
      "tk-ln" + (kind === "error" ? " tk-ln-err" : kind === "warn" ? " tk-ln-warn" : "");
    ln.textContent = text;
    logEl.appendChild(ln);
    logEl.scrollTop = logEl.scrollHeight;
  };

  cancelBtn.addEventListener("click", () => opts.onCancel?.());
  closeBtn.addEventListener("click", close);

  if (opts.attach !== false) document.body.appendChild(el);

  return { el, open, log, done, close };
}

/**
 * Stream a Server-Sent-Events endpoint into a progress view, mirroring scout's
 * streamJob: "line" events append a log line (lines matching /error|failed/ are
 * red, "warn:"-prefixed lines amber), an "end" event marks the run done. Returns
 * the EventSource so the caller can close it (e.g. on a cancel action).
 */
export function streamInto(p: ProgressHandle, url: string, title?: string): EventSource {
  p.open(title);
  const es = new EventSource(url);
  es.addEventListener("line", (e) => {
    const data = (e as MessageEvent).data as string;
    const isErr = /error|failed/i.test(data);
    const isWarn = !isErr && /^\s*warn:/i.test(data);
    p.log(isWarn ? data.replace(/^\s*warn:\s*/i, "⚠ ") : data, isErr ? "error" : isWarn ? "warn" : "info");
  });
  es.addEventListener("end", (e) => {
    const data = (e as MessageEvent).data as string;
    p.log(`— ${data} —`, data === "failed" ? "error" : "info");
    p.done();
    es.close();
  });
  es.onerror = () => es.close();
  return es;
}

/* ---- toast (transient notification — scout's toast()) -------------------- */

export type ToastKind = "info" | "success" | "error";
export type ToastOptions = {
  /** Override the auto-classified severity. */
  kind?: ToastKind;
  /** Auto-dismiss delay in ms (default 4000). Pass 0 to keep it until clicked. */
  durationMs?: number;
};

/**
 * Show a transient toast in a bottom-right stack (lazily created). Severity is
 * auto-classified from the text — anything matching
 * /fail|error|denied|invalid|unable|cannot/i tints red — unless `kind`
 * overrides it. Click to dismiss; returns a dismiss function. Mirrors scout's
 * toast() severity heuristic.
 */
export function toast(message: string, opts: ToastOptions = {}): () => void {
  const host = toastHost();
  const kind: ToastKind =
    opts.kind ?? (/fail|error|denied|invalid|unable|cannot/i.test(message) ? "error" : "info");
  const el = document.createElement("div");
  el.className = `tk-toast tk-toast-${kind}`;
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.textContent = message;
  host.appendChild(el);
  // Animate in on the next frame so the off-state is painted first.
  requestAnimationFrame(() => el.classList.add("tk-toast-in"));

  let dismissed = false;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    el.classList.remove("tk-toast-in");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
    setTimeout(() => el.remove(), 300); // fallback if no transition fires
  };
  el.addEventListener("click", dismiss);
  const dur = opts.durationMs ?? 4000;
  if (dur > 0) setTimeout(dismiss, dur);
  return dismiss;
}

/** The lazily-created singleton stack toasts append into. */
function toastHost(): HTMLElement {
  let host = document.querySelector<HTMLElement>(".tk-toast-host");
  if (!host) {
    host = document.createElement("div");
    host.className = "tk-toast-host";
    document.body.appendChild(host);
  }
  return host;
}
