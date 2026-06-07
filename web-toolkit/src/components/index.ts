/**
 * components — vanilla factories returning HTMLElement, harvested from scout's
 * internal/web/index.html primitives (button, card, table, modal, the SSE
 * progress drawer). NO third-party component library. Their CSS ships in the
 * toolkit's components.css — an app must
 *   import "@brainbot/web-toolkit/components.css";
 * for these to look right (base.css supplies the tokens they reference).
 */

/* ---- button (scout .btn) ------------------------------------------------- */

export type ButtonVariant = "default" | "primary" | "accent";
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
  el.textContent = opts.label;
  if (opts.disabled) el.disabled = true;
  if (opts.onClick) el.addEventListener("click", opts.onClick);
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

  wrap.appendChild(tbl);
  return wrap;
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

  const close = () => scrim.classList.remove("tk-open");
  const open = () => scrim.classList.add("tk-open");

  closeBtn.addEventListener("click", close);
  scrim.addEventListener("click", (e) => {
    if (e.target === scrim) close();
  });
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") close();
  };
  window.addEventListener("keydown", onKey);

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
