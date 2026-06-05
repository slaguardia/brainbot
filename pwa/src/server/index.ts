// Tiny Node server: serves the built static assets (in prod).
//
// The PWA is a thin consumer of the Python brain service. Free-text capture is
// currently DISABLED: with the document-substrate cutover the brain's write path
// is source ingest (Notion pages / docs), not a /capture endpoint — so this
// backend no longer proxies anything. POST /api/capture returns 410 Gone rather
// than calling a brain endpoint that no longer exists. (When a source-editing
// surface lands, the proxy comes back here.)
//
// In dev, Vite serves the client on :5173 and proxies /api/* to this
// process on :8787. In prod, this process serves both.

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.PORT ?? 8787);

// Brain service base. Reads are proxied here so the owner PWA can surface the
// brain's recall/map without the browser talking to the brain directly. Writes
// are never proxied — the PWA stays read-only against the brain.
const BRAIN = process.env.BRAIN_SERVICE_URL ?? "http://brain:8100";

const HERE = fileURLToPath(new URL(".", import.meta.url));
// In prod, dist-server/server/index.js sits next to ../../dist/ (Vite build output).
// In dev (tsx), src/server/index.ts sits next to ../../dist/ if a build exists,
// but dev usually goes through Vite on 5173 so static serving isn't exercised.
const STATIC_DIR = resolve(HERE, "..", "..", "dist");

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
};

function json(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

// Capture is retired with the document-substrate cutover (the brain's write path
// is source ingest, not /capture). Answer the legacy route with a clear 410 so a
// stale client gets an honest signal rather than a hung proxy to a dead endpoint.
function captureGone(res: ServerResponse): void {
  json(res, 410, {
    error: "capture is disabled",
    detail:
      "The brain now ingests sources (Notion pages / docs), not free text. " +
      "A source-editing surface is planned.",
  });
}

// GET-only read proxy to the brain. Forwards a fixed allow-list of query params
// to a brain read endpoint and streams back its JSON verbatim. On any fetch
// failure the brain is treated as unreachable (502) rather than hanging.
async function proxyRead(
  res: ServerResponse,
  url: URL,
  brainPath: string,
  params: readonly string[],
): Promise<void> {
  const target = new URL(brainPath, BRAIN);
  for (const p of params) {
    const v = url.searchParams.get(p);
    if (v !== null) target.searchParams.set(p, v);
  }
  // Bound the upstream call: undici's fetch has no default timeout, so a brain that
  // accepts the TCP connection but never responds (pool exhausted, blackholed host)
  // would otherwise hang the request — and the tab — forever. The abort lands in
  // the catch below as a 502, making the no-hang promise above actually true.
  const ac = new AbortController();
  const deadline = setTimeout(() => ac.abort(), 8000);
  try {
    const upstream = await fetch(target, { method: "GET", signal: ac.signal });
    const body = await upstream.text();
    res.writeHead(upstream.status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(body);
  } catch (err) {
    json(res, 502, { error: "brain unreachable", detail: String(err) });
  } finally {
    clearTimeout(deadline);
  }
}

async function serveStatic(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", "http://localhost");
  let rel = decodeURIComponent(url.pathname);
  if (rel.endsWith("/")) rel += "index.html";
  // Prevent path traversal: resolve within STATIC_DIR.
  const target = normalize(join(STATIC_DIR, rel));
  if (!target.startsWith(STATIC_DIR)) {
    res.writeHead(403).end("forbidden");
    return;
  }
  try {
    const s = await stat(target);
    if (s.isDirectory()) {
      res.writeHead(404).end("not found");
      return;
    }
    const body = await readFile(target);
    res.writeHead(200, {
      "Content-Type": MIME[extname(target)] ?? "application/octet-stream",
      "Cache-Control": rel === "/index.html" || rel === "/" ? "no-cache" : "public, max-age=3600",
    });
    res.end(body);
  } catch {
    // SPA fallback: serve index.html for unknown paths so client-side
    // routing (none today, but cheap to keep) survives. Skip for /api/*.
    if (rel.startsWith("/api/")) {
      res.writeHead(404).end("not found");
      return;
    }
    try {
      const body = await readFile(join(STATIC_DIR, "index.html"));
      res.writeHead(200, { "Content-Type": MIME[".html"], "Cache-Control": "no-cache" });
      res.end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  }
}

const server = createServer((req, res) => {
  if (!req.url) {
    res.writeHead(400).end();
    return;
  }
  const url = new URL(req.url, "http://localhost");
  if (req.method === "POST" && url.pathname === "/api/capture") {
    captureGone(res);
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/health") {
    json(res, 200, { ok: true });
    return;
  }
  // Owner read-views: recall search + source map, proxied GET-only to the brain.
  if (req.method === "GET" && url.pathname === "/api/recall") {
    void proxyRead(res, url, "/recall", ["q", "k", "scope", "min_score"]);
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/map") {
    void proxyRead(res, url, "/map", ["scope"]);
    return;
  }
  if (req.method === "GET" || req.method === "HEAD") {
    void serveStatic(req, res);
    return;
  }
  res.writeHead(405).end("method not allowed");
});

server.listen(PORT, () => {
  console.error(`[pwa] listening on :${PORT} (capture disabled — static serving only)`);
});
