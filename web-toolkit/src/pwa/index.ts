/**
 * pwa — manifest generator + service-worker registration, generalized from
 * brainbot's dashboard/public/manifest.webmanifest, dashboard/public/sw.js, and the SW
 * logic in dashboard/src/main.ts.
 *
 * The standard service worker ships in this package at src/pwa/sw.js. An app
 * must place a copy at its own origin as `/sw.js` (a service worker can only
 * control the scope it is served from). The simplest wiring — documented in the
 * README — is for the app to copy the file into its `public/` so Vite emits it
 * to `dist/sw.js`. The vite-preset re-exports the file path for that copy step.
 */

export type ManifestIcon = {
  src: string;
  sizes: string;
  type: string;
  purpose?: string;
};

export type ManifestOptions = {
  name: string;
  short_name: string;
  description?: string;
  /** App identity — the ONE per-app palette override allowed. Defaults to --bg. */
  themeColor?: string;
  backgroundColor?: string;
  icons?: ManifestIcon[];
};

/** The fields we emit; a structural subset of the W3C WebAppManifest. */
export type WebManifest = {
  name: string;
  short_name: string;
  description?: string;
  start_url: string;
  scope: string;
  display: "standalone";
  orientation: "portrait";
  background_color: string;
  theme_color: string;
  icons: ManifestIcon[];
};

const DEFAULT_ICONS: ManifestIcon[] = [
  { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
  { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
];

/**
 * Build a web app manifest object. Generated at build time — an app writes the
 * result to public/manifest.webmanifest (or has its build step do it). Defaults
 * mirror the donor manifest: dark theme/background from the palette, standalone
 * portrait, the conventional 192/512 icons.
 */
export function manifest(opts: ManifestOptions): WebManifest {
  return {
    name: opts.name,
    short_name: opts.short_name,
    ...(opts.description ? { description: opts.description } : {}),
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: opts.backgroundColor ?? "#0b0d12",
    theme_color: opts.themeColor ?? "#0b0d12",
    icons: opts.icons ?? DEFAULT_ICONS,
  };
}

/**
 * Register the app-shell service worker in production; self-heal in dev.
 *
 * Lifted from dashboard/src/main.ts: on localhost the SW cache just masks fresh dev
 * builds, so instead of registering we tear down any SW + caches a prior visit
 * left behind. In production we register `/sw.js` on load (a failure is
 * non-fatal). The app must have a `/sw.js` at its origin (see module docs).
 */
export function registerSW(): void {
  if (!("serviceWorker" in navigator)) return;

  const onLocalhost = ["localhost", "127.0.0.1", "[::1]", ""].includes(location.hostname);
  if (onLocalhost) {
    void navigator.serviceWorker.getRegistrations().then((regs) => {
      for (const r of regs) void r.unregister();
    });
    if (window.caches) {
      void caches.keys().then((keys) => {
        for (const k of keys) void caches.delete(k);
      });
    }
    return;
  }

  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      // SW failure is non-fatal — the app still works online.
    });
  });
}
