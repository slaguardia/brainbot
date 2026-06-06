// Vite `?raw` imports — the canonical repo docs bundled as strings (docs.ts).
declare module "*.md?raw" {
  const text: string;
  export default text;
}
