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
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
