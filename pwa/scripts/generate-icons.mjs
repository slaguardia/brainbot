#!/usr/bin/env node
// Rasterize static/favicon.svg into the PNG icons referenced from
// static/manifest.webmanifest.
//
// Maskable icon gets 20% padding inside the 512px canvas so iOS/Android
// safe-area cropping doesn't clip the design.
//
// Run: node scripts/generate-icons.mjs (or `npm run icons`).

import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Resvg } from '@resvg/resvg-js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

const SOURCE = join(ROOT, 'static', 'favicon.svg');

const TARGETS = [
  { out: 'icon-192.png', width: 192 },
  { out: 'icon-512.png', width: 512 },
  { out: 'icon-maskable-512.png', width: 512, maskablePad: 0.1 } // 10% pad each side
];

const svgRaw = await readFile(SOURCE, 'utf8');

for (const target of TARGETS) {
  let svg = svgRaw;
  if (target.maskablePad) {
    // Wrap the original in an outer SVG with a solid background and inset
    // the original by the padding. The base svg's viewBox is "0 0 64 64".
    const inset = 64 * target.maskablePad;
    const inner = 64 - inset * 2;
    svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" fill="#5B6CFF"/>
  <svg x="${inset}" y="${inset}" width="${inner}" height="${inner}" viewBox="0 0 64 64">
    ${svgRaw.replace(/<svg[^>]*>/, '').replace(/<\/svg>/, '')}
  </svg>
</svg>`;
  }

  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: target.width }
  });
  const png = resvg.render().asPng();
  await writeFile(join(ROOT, 'static', target.out), png);
  console.log(`✓ ${target.out} (${target.width}×${target.width}, ${png.length} bytes)`);
}
