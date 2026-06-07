/**
 * Design tokens — the canonical palette/space/motion contract.
 *
 * `base.css` is the PRIMARY contract: an app does
 *   import "@brainbot/web-toolkit/base.css";
 * once, and every variable below is then available as a CSS custom property on
 * :root. This module exposes the same names as a typed record so app TS can
 * reference a token without stringly-typing it, e.g.
 *   el.style.color = cssVar(tokens.fgMuted);
 *
 * These mirror pwa/src/style.css's :root block. base.css is the source of
 * truth for the VALUES; this file is the source of truth for the NAMES.
 */

/** A CSS custom-property name, including the leading `--`. */
export type TokenVar = `--${string}`;

export const tokens = {
  // Surfaces
  bg: "--bg",
  bg2: "--bg-2",
  bgElevated: "--bg-elevated",
  panel2: "--panel-2",
  panel3: "--panel-3",
  // Text
  fg: "--fg",
  fgMuted: "--fg-muted",
  fgFaint: "--fg-faint",
  // Lines
  border: "--border",
  borderStrong: "--border-strong",
  // Brand + interactive
  accent: "--accent",
  accentPress: "--accent-press",
  link: "--link",
  linkBg: "--link-bg",
  // Semantic signal
  yes: "--yes",
  yesBg: "--yes-bg",
  maybe: "--maybe",
  maybeBg: "--maybe-bg",
  no: "--no",
  noBg: "--no-bg",
  error: "--error",
  errorBg: "--error-bg",
  // Radius
  rSm: "--r-sm",
  rMd: "--r-md",
  rLg: "--r-lg",
  rXl: "--r-xl",
  // Motion
  ease: "--ease",
  durFast: "--dur-fast",
  durBase: "--dur-base",
  durSlow: "--dur-slow",
  // Shadows
  shadowSm: "--shadow-sm",
  shadowMd: "--shadow-md",
  shadowLg: "--shadow-lg",
  // Fonts
  fontUi: "--font-ui",
  fontMono: "--font-mono",
} as const satisfies Record<string, TokenVar>;

export type TokenName = keyof typeof tokens;

/** Wrap a token name in `var(...)` for use in a style string. */
export function cssVar(name: TokenVar): string {
  return `var(${name})`;
}
