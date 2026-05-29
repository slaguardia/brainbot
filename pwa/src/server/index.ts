// Tiny Node server: serves the built static assets (in prod) and proxies
// POST /api/capture to the brain service, which does the decompose + ingest.
//
// The PWA backend is intentionally dumb now — all brain smarts (decomposition,
// extraction tuning, direct graphiti-core access) live in the Python brain
// service. This is the "thin consumer, smart brain" split the project is built
// around. We used to talk MCP JSON-RPC straight to graphiti; that path (and
// brain.ts) is gone.
//
// In dev, Vite serves the client on :5173 and proxies /api/* to this
// process on :8787. In prod, this process serves both.

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.PORT ?? 8787);
const BRAIN_SERVICE_URL = (process.env.BRAIN_SERVICE_URL ?? "http://127.0.0.1:8100").replace(/\/$/, "");

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

async function readBody(req: IncomingMessage, limit = 64 * 1024): Promise<string> {
  return new Promise((resolveBody, rejectBody) => {
    let size = 0;
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => {
      size += c.length;
      if (size > limit) {
        rejectBody(new Error("payload too large"));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolveBody(Buffer.concat(chunks).toString("utf8")));
    req.on("error", rejectBody);
  });
}

function json(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

async function handleCapture(req: IncomingMessage, res: ServerResponse): Promise<void> {
  let raw: string;
  try {
    raw = await readBody(req);
  } catch (err) {
    json(res, 413, { error: (err as Error).message });
    return;
  }
  let payload: { text?: unknown };
  try {
    payload = JSON.parse(raw) as { text?: unknown };
  } catch {
    json(res, 400, { error: "invalid JSON" });
    return;
  }
  const text = typeof payload.text === "string" ? payload.text.trim() : "";
  if (!text) {
    json(res, 400, { error: "text is required" });
    return;
  }

  // Proxy to the brain service, which decomposes + ingests. Capture is slow
  // (decompose + N extraction passes), but the PWA client acks optimistically,
  // so the user never waits on this round-trip.
  const startedAt = Date.now();
  console.error(`[capture] start chars=${text.length}`);
  try {
    const upstream = await fetch(`${BRAIN_SERVICE_URL}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const result = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
    if (!upstream.ok) {
      console.error(`[capture] done  ms=${Date.now() - startedAt} status=err http=${upstream.status}`);
      json(res, 502, { error: "brain write failed", detail: result });
      return;
    }
    console.error(`[capture] done  ms=${Date.now() - startedAt} status=ok ${JSON.stringify(result)}`);
    json(res, 202, { ok: true, ...result });
  } catch (err) {
    console.error(`[capture] done  ms=${Date.now() - startedAt} status=err ${(err as Error).message}`);
    json(res, 502, { error: "brain unreachable", detail: (err as Error).message });
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
    void handleCapture(req, res);
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/health") {
    json(res, 200, { ok: true });
    return;
  }
  if (req.method === "GET" || req.method === "HEAD") {
    void serveStatic(req, res);
    return;
  }
  res.writeHead(405).end("method not allowed");
});

server.listen(PORT, () => {
  console.error(`[pwa] listening on :${PORT} brain_service=${BRAIN_SERVICE_URL}`);
});
