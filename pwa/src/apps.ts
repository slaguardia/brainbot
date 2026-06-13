// The apps-home launcher (`#apps`) — the brainbot PWA's view of every app on the
// brain platform. Renders one card per registry entry (apps.json, hand-curated
// config — NOT brain data), health-pings each app's `health` URL to show
// connected / offline, and links out to each app's own origin.
//
// Why it only LINKS OUT and never installs: a PWA's `beforeinstallprompt` is
// per-origin, so a launcher cannot install another app's PWA for you — install
// happens at each app's own page. The card's "Open" link takes you there; you
// install the PWA at that origin. (See docs/app-platform.md "The launcher".)
//
// This is an app-layer feature: the brain SERVICE exposes no launcher/HTML — the
// launcher lives entirely in this PWA. All registry strings are escaped before
// they touch innerHTML (config is text, never markup), matching home/discover.

import { card } from "@brainbot/web-toolkit/components";

import registry from "./apps.json";

interface AppEntry {
  name: string;
  short_name: string;
  icon: string;
  url: string;
  health: string;
}

const APPS: AppEntry[] = registry.apps;

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// First letter of the app name, for the monogram fallback when an icon is
// missing or fails to load (so the launcher never depends on committed PNGs).
function monogram(name: string): string {
  const c = name.trim()[0];
  return esc(c ? c.toUpperCase() : "?");
}

export function mountApps(container: HTMLElement): void {
  // The shared header/nav chrome is rendered by the toolkit shell (mountApp);
  // this view renders only its body into the content region.
  container.innerHTML = `
    <section class="home apps">
      <div class="apps-head">
        <h2>Apps</h2>
      </div>
      <p class="apps-sub">
        Apps on the brain platform. Each opens at its own origin — where you
        install its PWA. (A launcher can't install another app's PWA for you:
        <code>beforeinstallprompt</code> is per-origin.)
      </p>
      <div class="apps-grid"></div>
    </section>`;

  const grid = container.querySelector<HTMLElement>(".apps-grid")!;
  if (APPS.length === 0) {
    grid.innerHTML = `<p class="home-status">No apps registered yet.</p>`;
    return;
  }
  for (const app of APPS) {
    const c = card({ body: appCardBody(app) });
    c.classList.add("app-card");
    grid.appendChild(c);
    void pingHealth(c, app.health);
  }
}

// One card's inner markup: monogram/icon, name + short_name, a health pill that
// starts in a neutral "checking" state, and the Open link out to the app's url.
// The host app itself (registry url "/" — this launcher's own origin) gets a
// muted "this app" marker instead of an Open link: there's nowhere to open to.
function appCardBody(app: AppEntry): HTMLElement {
  const isSelf = app.url === "/";
  const action = isSelf
    ? `<span class="app-here">this app</span>`
    : `<a class="app-open" href="${esc(app.url)}" rel="noopener">Open ↗</a>`;
  const el = document.createElement("div");
  el.innerHTML = `
    <div class="app-card-top">
      <span class="app-icon" aria-hidden="true">${monogram(app.name)}</span>
      <span class="app-names">
        <span class="app-name">${esc(app.name)}</span>
        <span class="app-short">${esc(app.short_name)}</span>
      </span>
    </div>
    <div class="app-card-foot">
      <span class="app-health is-checking" role="status">checking…</span>
      ${action}
    </div>`;
  // Swap the monogram for the real icon if it loads; on error the monogram
  // stays — no dependency on uncommitted PNG assets.
  if (app.icon) {
    const span = el.querySelector<HTMLElement>(".app-icon")!;
    const img = new Image();
    img.alt = "";
    img.onload = () => {
      span.textContent = "";
      span.appendChild(img);
    };
    img.src = app.icon;
  }
  return el;
}

// Health-ping: any non-ok / rejection / timeout reads as offline; a 200 reads as
// connected. A short AbortController deadline keeps an unreachable host (scout's
// example URL in dev) from leaving the pill stuck on "checking…".
async function pingHealth(cardEl: HTMLElement, url: string): Promise<void> {
  const pill = cardEl.querySelector<HTMLElement>(".app-health");
  if (!pill) return;
  const ac = new AbortController();
  const deadline = setTimeout(() => ac.abort(), 4000);
  let ok = false;
  try {
    const res = await fetch(url, { method: "GET", signal: ac.signal });
    ok = res.ok;
  } catch {
    ok = false;
  } finally {
    clearTimeout(deadline);
  }
  pill.classList.remove("is-checking");
  if (ok) {
    pill.classList.add("is-connected");
    pill.textContent = "connected";
  } else {
    pill.classList.add("is-offline");
    pill.textContent = "offline";
  }
}
