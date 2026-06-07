// @brainbot/web-toolkit — standard app-shell service worker.
//
// Generalized from brainbot's pwa/public/sw.js. Pre-caches the index page +
// built static assets so the icon launches fast and works briefly offline.
// /api/* and /oauth2/* are NEVER cached — always hit the network (the brain
// proxy and auth must stay live). Navigations are network-first (a new deploy
// shows on the next load); hashed assets are cache-first (immutable by name).
//
// HOW AN APP USES THIS: copy this file to your origin as /sw.js (the simplest
// path is to drop it in your Vite `public/` so it is emitted to dist/sw.js).
// The cache name is parameterized: change CACHE per app (and bump the version
// suffix on a breaking shell change) so each app's cache is isolated.
const CACHE = "app-shell-v1";

// SHELL is the must-cache core; OPTIONAL is best-effort (a missing icon must not
// fail the whole install).
const SHELL = ["/", "/manifest.webmanifest"];
const OPTIONAL = ["/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then(async (cache) => {
        await cache.addAll(SHELL);
        await Promise.all(
          OPTIONAL.map((url) =>
            fetch(url)
              .then((res) => (res.ok ? cache.put(url, res) : null))
              .catch(() => null),
          ),
        );
      })
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/oauth2/"))
    return;

  // The HTML document (a navigation) is served NETWORK-FIRST so a new deploy is
  // picked up on the next load; the cached copy is only an offline fallback.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok && url.origin === self.location.origin) {
            const clone = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, clone));
          }
          return res;
        })
        .catch(() => caches.match(req).then((c) => c || caches.match("/"))),
    );
    return;
  }

  // Hashed build assets are immutable by filename, so cache-first is safe here.
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req)
        .then((res) => {
          if (res.ok && url.origin === self.location.origin) {
            const clone = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, clone));
          }
          return res;
        })
        .catch(() => caches.match("/"));
    }),
  );
});
