/**
 * shell — the app chrome + hash router, generalized from brainbot's
 * pwa/src/main.ts.
 *
 * `mountApp(routes, opts)` renders the shared chrome (a `.cap-head` with a brand
 * wordmark + `.cap-nav` pills, and a `.tk-content` <main> region) once, then
 * hash-routes into the content region: on load and on every `hashchange` it
 * picks the longest route key that prefixes `location.hash`, calls that route's
 * factory to get a fresh View, and mounts it. Re-invoking the factory on every
 * navigation is deliberate — it matches the donor's "re-fetch on return"
 * behaviour so views pick up data changed elsewhere.
 *
 * The chrome's CSS lives in the toolkit's base.css (chrome is shared shell);
 * app-view CSS stays in the app.
 */

/** A mountable view. The factory in the routes map returns one of these. */
export type View = { mount(el: HTMLElement): void | Promise<void> };

/**
 * A route entry. The common form is a bare view factory (`() => View`), which
 * renders inside the shared chrome (header/nav + the guttered `.tk-content`).
 * The object form lets a route opt OUT of that chrome (`chrome: false`) so the
 * view owns the full viewport — for a route with its own distinct layout (e.g.
 * a full-bleed knowledge-base page). Backward compatible: existing routes that
 * pass a factory keep the chrome.
 */
export type RouteEntry = (() => View) | { view: () => View; chrome?: boolean };

/** A nav pill in the header. `href` is a hash, e.g. "#docs". */
export type NavItem = { label: string; href: string; ariaLabel?: string };

export type MountAppOptions = {
  /** Wordmark shown in the header brand slot. Defaults to document.title. */
  title?: string;
  /** Header nav pills. */
  nav?: NavItem[];
  /** Where the brand wordmark links. Defaults to "#" (home). */
  brandHref?: string;
  /** Element to render the shell into. Defaults to document.body. */
  root?: HTMLElement;
};

/**
 * Pick the route whose key is the LONGEST prefix of the current hash. An empty
 * key "" is the catch-all home route. The hash is compared without its leading
 * "#", matching the donor's `location.hash.replace(/^#/, "")`.
 */
function matchRoute(routes: Record<string, RouteEntry>, hash: string): string | null {
  const path = hash.replace(/^#/, "");
  let best: string | null = null;
  for (const key of Object.keys(routes)) {
    if (path === key || path.startsWith(key)) {
      if (best === null || key.length > best.length) best = key;
    }
  }
  // Fall back to the home route "" if present and nothing else matched.
  if (best === null && "" in routes) best = "";
  return best;
}

/** Normalize a route entry to { view, chrome } (chrome defaults to true). */
function resolveEntry(entry: RouteEntry): { view: () => View; chrome: boolean } {
  if (typeof entry === "function") return { view: entry, chrome: true };
  return { view: entry.view, chrome: entry.chrome !== false };
}

export function mountApp(
  routes: Record<string, RouteEntry>,
  opts: MountAppOptions = {},
): void {
  const root = opts.root ?? document.body;
  const title = opts.title ?? document.title ?? "";
  const brandHref = opts.brandHref ?? "#";

  const main = document.createElement("main");

  const head = document.createElement("header");
  head.className = "cap-head";
  const brand = document.createElement("a");
  brand.className = "brand";
  brand.href = brandHref;
  brand.textContent = title;
  brand.setAttribute("aria-label", `${title} — home`);
  head.appendChild(brand);

  const navEl = document.createElement("nav");
  navEl.className = "cap-nav";
  navEl.setAttribute("aria-label", "Views");
  for (const item of opts.nav ?? []) {
    const a = document.createElement("a");
    a.href = item.href;
    a.textContent = item.label;
    if (item.ariaLabel) a.setAttribute("aria-label", item.ariaLabel);
    navEl.appendChild(a);
  }
  head.appendChild(navEl);

  const content = document.createElement("section");
  content.className = "tk-content";

  main.appendChild(head);
  main.appendChild(content);

  // A separate mount target for chrome:false routes — they render full-bleed,
  // outside the guttered <main>/header, owning the viewport themselves.
  const bleed = document.createElement("div");
  bleed.className = "tk-bleed";

  // Mark the active nav pill for the current hash.
  const markActive = (matched: string | null) => {
    for (const a of Array.from(navEl.querySelectorAll("a"))) {
      const itemPath = a.getAttribute("href")?.replace(/^#/, "") ?? "";
      a.toggleAttribute("aria-current", matched !== null && matched !== "" && itemPath === matched);
      if (a.hasAttribute("aria-current")) a.setAttribute("aria-current", "page");
    }
  };

  let token = 0;
  const route = () => {
    const matched = matchRoute(routes, location.hash);
    markActive(matched);
    if (matched === null) {
      if (bleed.isConnected) bleed.remove();
      if (!main.isConnected) root.appendChild(main);
      setEmpty(content, "Not found.");
      return;
    }
    const { view, chrome } = resolveEntry(routes[matched]);
    // Swap which container is in the document so a chrome:false route is never
    // boxed by the chrome's <main> gutters, and vice-versa.
    const target = chrome ? content : bleed;
    if (chrome) {
      if (bleed.isConnected) bleed.remove();
      if (!main.isConnected) root.appendChild(main);
    } else {
      if (main.isConnected) main.remove();
      if (!bleed.isConnected) root.appendChild(bleed);
    }
    target.replaceChildren();
    const v = view();
    // Guard against an async mount being clobbered by a later navigation.
    const mine = ++token;
    const result = v.mount(target);
    if (result instanceof Promise) {
      result.catch((err) => {
        if (mine === token) setError(target, String(err));
      });
    }
  };

  window.addEventListener("hashchange", route);
  route();
}

/* ---- standard view states ------------------------------------------------ */

/** Replace `el` with a spinner + optional message. */
export function setLoading(el: HTMLElement, msg = "Loading…"): void {
  el.replaceChildren();
  const row = document.createElement("div");
  row.className = "tk-loading";
  const spin = document.createElement("span");
  spin.className = "tk-spinner";
  row.appendChild(spin);
  row.appendChild(document.createTextNode(msg));
  el.appendChild(row);
}

/** Replace `el` with a centred empty-state message. */
export function setEmpty(el: HTMLElement, msg: string): void {
  el.replaceChildren();
  const box = document.createElement("div");
  box.className = "tk-empty";
  box.textContent = msg;
  el.appendChild(box);
}

/** Replace `el` with an error banner. */
export function setError(el: HTMLElement, msg: string): void {
  el.replaceChildren();
  const box = document.createElement("div");
  box.className = "tk-error";
  box.textContent = msg;
  el.appendChild(box);
}
