# App icons

PNG icons referenced in `manifest.webmanifest` are committed and generated
from `favicon.svg` by `scripts/generate-icons.mjs`.

To regenerate (after changing the SVG):

```bash
npm run icons
```

The maskable variant adds 10% padding inside the canvas so iOS/Android
safe-area cropping doesn't clip the design.
