# App icons

PNG icons referenced in `manifest.webmanifest` are not committed because they
need to be designed. Until they exist:

- iOS "Add to Home Screen" will fall back to a screenshot.
- Lighthouse PWA audit will warn about missing icons.

When you're ready, generate from `favicon.svg`:

```bash
# Requires imagemagick or rsvg-convert
rsvg-convert -w 192 -h 192 favicon.svg -o icon-192.png
rsvg-convert -w 512 -h 512 favicon.svg -o icon-512.png
# For maskable, add a 20% safe-area padding around the design
rsvg-convert -w 512 -h 512 favicon.svg -o icon-maskable-512.png
```

Or use https://realfavicongenerator.net/ for one-shot generation.
