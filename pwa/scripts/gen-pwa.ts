// Prebuild step: generate the PWA manifest from the toolkit and copy the
// toolkit's standard service worker into public/ so Vite emits dist/sw.js.
// Both files are build artifacts (gitignored) — the toolkit is the single
// source of truth for the manifest shape + the SW. Values mirror the donor
// manifest (name/short_name/description, dark theme from the palette) so the
// installed-app identity is unchanged.
import { writeFileSync, copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { manifest } from "@brainbot/web-toolkit/pwa";
import { swSource } from "@brainbot/web-toolkit/vite-preset";

const here = dirname(fileURLToPath(import.meta.url));
const publicDir = resolve(here, "..", "public");
mkdirSync(publicDir, { recursive: true });

writeFileSync(
  resolve(publicDir, "manifest.webmanifest"),
  JSON.stringify(
    manifest({
      name: "Brain",
      short_name: "Brain",
      description: "Two-second capture to the brain.",
    }),
    null,
    2,
  ),
);
copyFileSync(swSource, resolve(publicDir, "sw.js"));
