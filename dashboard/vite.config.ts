import { defineConfig, mergeConfig } from "vite";
import { toolkitVite } from "@brainbot/web-toolkit/vite-preset";

// The toolkit preset standardizes the dev /api proxy, fs.allow ".." (so docs.ts's
// ../../docs/*.md?raw imports resolve), and the dist build. The backend listens on
// :8787, so point the dev proxy there.
export default mergeConfig(
  toolkitVite({ apiProxyTarget: "http://127.0.0.1:8787" }),
  defineConfig({
    // app-specific overrides only
  }),
);
