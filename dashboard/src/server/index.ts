// Tiny Node server: serves the built static assets (in prod).
//
// The dashboard backend is a thin consumer of the Python brain service. Free-text capture is
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

// Brain service base. Reads are proxied here (GET /api/brain/recall|doc|map|changes)
// so the owner dashboard can surface the brain's recall/doc/map without the browser
// talking to the brain directly. The one proxied write is POST /api/ingest — the
// discovery view's "pull this page into the brain" action, forwarding to the
// brain's existing /ingest. Free-text capture stays disabled.
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
  timeoutMs = 8000,
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
  const deadline = setTimeout(() => ac.abort(), timeoutMs);
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

// POST proxy for the discovery view's ingest action: forward the JSON body to
// the brain's /ingest verbatim. A longer deadline than the read proxy — ingest
// walks the page's block tree and embeds its chunks, which takes real seconds.
async function proxyIngest(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const body = await new Promise<string>((resolve, reject) => {
    const parts: Buffer[] = [];
    req.on("data", (c: Buffer) => parts.push(c));
    req.on("end", () => resolve(Buffer.concat(parts).toString("utf-8")));
    req.on("error", reject);
  }).catch(() => null);
  if (body === null) {
    json(res, 400, { error: "could not read request body" });
    return;
  }
  const ac = new AbortController();
  const deadline = setTimeout(() => ac.abort(), 60_000);
  try {
    const upstream = await fetch(new URL("/ingest", BRAIN), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: ac.signal,
    });
    const text = await upstream.text();
    res.writeHead(upstream.status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(text);
  } catch (err) {
    json(res, 502, { error: "brain unreachable", detail: String(err) });
  } finally {
    clearTimeout(deadline);
  }
}

// Body-forwarding proxy for the Integrations surface: PUT (connect — body is the
// token) and DELETE (disconnect — no body) to the brain's /integrations/notion.
// The token only ever travels browser→this server→brain; it's never stored or
// echoed client-side.
async function proxyJson(
  req: IncomingMessage,
  res: ServerResponse,
  method: "GET" | "POST" | "PUT" | "DELETE",
  brainPath: string,
  timeoutMs = 15_000,
): Promise<void> {
  // Only PUT carries a body in our surface (connect token, settings, policy). POST
  // (manual rewrite) and GET (diff read) forward bodiless; DELETE forwards bodiless.
  let body: string | undefined;
  if (method === "PUT") {
    const read = await new Promise<string>((resolve, reject) => {
      const parts: Buffer[] = [];
      req.on("data", (c: Buffer) => parts.push(c));
      req.on("end", () => resolve(Buffer.concat(parts).toString("utf-8")));
      req.on("error", reject);
    }).catch(() => null);
    if (read === null) {
      json(res, 400, { error: "could not read request body" });
      return;
    }
    body = read;
  }
  const ac = new AbortController();
  const deadline = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const upstream = await fetch(new URL(brainPath, BRAIN), {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body,
      signal: ac.signal,
    });
    const text = await upstream.text();
    res.writeHead(upstream.status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(text);
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
  // Identity: echo the email the edge's oauth2-proxy injected as
  // X-Auth-Request-Email. With no edge in front (local dev) the header is absent
  // and we return {} — the toolkit's currentUser() then resolves to null (no
  // login UI). Never trust a client-supplied value; this header is set edge-side.
  if (req.method === "GET" && url.pathname === "/api/me") {
    const email = req.headers["x-auth-request-email"];
    json(res, 200, typeof email === "string" && email ? { email } : {});
    return;
  }
  // Owner read-views: the toolkit brain client (recall / doc / map / changes)
  // calls these /api/brain/* routes; we proxy GET-only to the brain, bearer + URL
  // server-side.
  if (req.method === "GET" && url.pathname === "/api/brain/recall") {
    void proxyRead(res, url, "/recall", ["q", "k", "scope", "complete"]);
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/brain/doc") {
    void proxyRead(res, url, "/doc", ["id"]);
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/brain/map") {
    void proxyRead(res, url, "/map", ["scope"]);
    return;
  }
  // Tier 0 change signal: the toolkit's onChange() polls this to know when a
  // cached view is stale. One cheap call, no LLM — forwards the `since` cursor.
  if (req.method === "GET" && url.pathname === "/api/brain/changes") {
    void proxyRead(res, url, "/changes", ["since"]);
    return;
  }
  // Discovery: every Notion page the integration can see, flagged ingested/not.
  // Longer deadline — the brain pages through Notion's search API upstream.
  if (req.method === "GET" && url.pathname === "/api/notion/pages") {
    void proxyRead(res, url, "/notion/pages", [], 30_000);
    return;
  }
  // Selective pull: the discovery view's per-page ingest action.
  if (req.method === "POST" && url.pathname === "/api/ingest") {
    void proxyIngest(req, res);
    return;
  }
  // Revoke: the discovery view's per-page un-ingest action — drop the source
  // (and its chunks) from the brain. The inverse of /api/ingest.
  if (req.method === "DELETE" && url.pathname.startsWith("/api/sources/")) {
    const id = url.pathname.slice("/api/sources/".length);
    if (!/^[0-9a-fA-F-]{36}$/.test(id)) {
      json(res, 400, { error: "id must be a uuid" });
      return;
    }
    void proxyJson(req, res, "DELETE", `/sources/${id}`);
    return;
  }
  // Note-legibility owner actions on one source: the diff read (GET) + manual
  // rewrite trigger (POST) at /api/sources/{id}/rewrite, and the per-source policy
  // pin (PUT) at /api/sources/{id}/rewrite-policy.
  if (url.pathname.startsWith("/api/sources/")) {
    const rest = url.pathname.slice("/api/sources/".length); // "<id>/rewrite" etc.
    const slash = rest.indexOf("/");
    if (slash > 0) {
      const id = rest.slice(0, slash);
      const action = rest.slice(slash + 1);
      if (!/^[0-9a-fA-F-]{36}$/.test(id)) {
        json(res, 400, { error: "id must be a uuid" });
        return;
      }
      if (action === "rewrite" && (req.method === "GET" || req.method === "POST")) {
        void proxyJson(req, res, req.method, `/sources/${id}/rewrite`);
        return;
      }
      if (action === "rewrite-policy" && req.method === "PUT") {
        void proxyJson(req, res, "PUT", `/sources/${id}/rewrite-policy`);
        return;
      }
    }
  }
  // Integrations: connection status (GET) + connect/disconnect Notion (PUT/DELETE).
  if (req.method === "GET" && url.pathname === "/api/integrations") {
    void proxyRead(res, url, "/integrations", []);
    return;
  }
  if (
    url.pathname === "/api/integrations/notion" &&
    (req.method === "PUT" || req.method === "DELETE")
  ) {
    void proxyJson(req, res, req.method, "/integrations/notion");
    return;
  }
  // Auto-sync interval: set (PUT) or revert to env (DELETE) the Notion poll loop.
  if (
    url.pathname === "/api/integrations/notion/sync" &&
    (req.method === "PUT" || req.method === "DELETE")
  ) {
    void proxyJson(req, res, req.method, "/integrations/notion/sync");
    return;
  }
  // Note-legibility policy: set fields (PUT) or reset to defaults (DELETE).
  if (
    url.pathname === "/api/integrations/legibility" &&
    (req.method === "PUT" || req.method === "DELETE")
  ) {
    void proxyJson(req, res, req.method, "/integrations/legibility");
    return;
  }
  // Anthropic API key: set/validate (PUT, body is the key) or remove (DELETE). A
  // stored key overrides the ANTHROPIC_API_KEY env on the brain. Status is read
  // back via GET /api/integrations (has_key + key_source), never the key itself.
  if (
    url.pathname === "/api/integrations/anthropic" &&
    (req.method === "PUT" || req.method === "DELETE")
  ) {
    void proxyJson(req, res, req.method, "/integrations/anthropic");
    return;
  }
  if (req.method === "GET" || req.method === "HEAD") {
    void serveStatic(req, res);
    return;
  }
  res.writeHead(405).end("method not allowed");
});

server.listen(PORT, () => {
  console.error(`[dashboard] listening on :${PORT} (capture disabled; reads + ingest proxied to ${BRAIN})`);
});
