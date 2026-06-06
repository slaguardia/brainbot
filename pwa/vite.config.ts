import { defineConfig } from "vite";

// Vite dev server proxies /api/* to the Node backend on :8787.
// In prod the same Node process serves the built static assets, so the
// proxy isn't needed.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
    },
    fs: {
      // docs.ts imports ../docs/*.md?raw from the repo root (the canonical
      // docs rendered in the #docs view) — allow the dev server to serve them.
      allow: [".", ".."],
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
