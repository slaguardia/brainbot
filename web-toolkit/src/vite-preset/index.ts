/**
 * vite-preset — the shared Vite config base every app extends, generalized from
 * brainbot's dashboard/vite.config.ts.
 *
 * An app's vite.config.ts merges this:
 *
 *   import { defineConfig, mergeConfig } from "vite";
 *   import { toolkitVite } from "@brainbot/web-toolkit/vite-preset";
 *   export default mergeConfig(toolkitVite(), defineConfig({ ...app overrides }));
 *
 * What it standardizes:
 *  - dev: proxy /api/* to the app's backend (default :8787, override via opts)
 *  - dev: fs.allow ".." so `?raw` imports (e.g. ../docs/*.md) resolve
 *  - build: outDir "dist", emptyOutDir
 *
 * Vite handles `?raw` imports natively, so the donor's markdown-as-raw pattern
 * needs no plugin — only the fs.allow above when the files live outside the web
 * root. The standard service worker is NOT bundled by Vite; an app copies
 * `swSource` (re-exported below) into its public/ so it is emitted as
 * dist/sw.js. registerSW() (from "@brainbot/web-toolkit/pwa") then loads it.
 */
import type { UserConfig } from "vite";

export type ToolkitViteOptions = {
  /** Backend the dev server proxies /api/* to. Default "http://127.0.0.1:8787". */
  apiProxyTarget?: string;
  /** Dev server port. Default 5173. */
  port?: number;
};

export function toolkitVite(opts: ToolkitViteOptions = {}): UserConfig {
  return {
    server: {
      port: opts.port ?? 5173,
      proxy: {
        "/api": opts.apiProxyTarget ?? "http://127.0.0.1:8787",
      },
      fs: {
        // Allow `?raw` imports from outside the web root (e.g. ../docs/*.md).
        allow: [".", ".."],
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
}

/**
 * Absolute path to the toolkit's standard service worker, for an app's build to
 * copy into its public/ (so Vite emits dist/sw.js). Example copy step in an
 * app's package.json:
 *   "prebuild": "node -e \"import('@brainbot/web-toolkit/vite-preset').then(m=>require('fs').copyFileSync(m.swSource,'public/sw.js'))\""
 */
export const swSource = new URL("../pwa/sw.js", import.meta.url).pathname;
