// App entry: skin + shell + offline plumbing come from @brainbot/web-toolkit;
// this file wires the brainbot views into the toolkit's hash router.
//
// base.css gives the palette + base resets + shared chrome (.cap-head/.cap-nav/
// .brand); components.css backs the toolkit component factories; style.css holds
// the app-view CSS the toolkit doesn't provide (home/docs/discover). mountApp
// renders the shared header/nav once and hash-routes into a content region —
// re-invoking the matched view's factory on every navigation, which preserves
// the donor's "re-fetch on return" behaviour (home re-reads /api/brain/map when
// you come back from #discover). registerSW() registers /sw.js in production and
// self-heals on localhost.
//
// Routes:
//   ''                 → home hub (stats + embedded recall search + source map)
//   docs / learnings   → in-app knowledge base (its own full-bleed KB layout, so
//                        chrome:false — no shared header/gutters). `#learnings*`
//                        aliases onto the docs view's Evolution page.
//   discover           → Notion discovery (pull pages into the brain)
//   integrations       → connect outside sources (Notion token) from the UI
//   apps               → apps-home launcher (cards for every platform app)

import "@brainbot/web-toolkit/base.css";
import "@brainbot/web-toolkit/components.css";
import "./style.css";
import { mountApp } from "@brainbot/web-toolkit/shell";
import { registerSW } from "@brainbot/web-toolkit/pwa";

import { mountApps } from "./apps";
import { mountDiscover } from "./discover";
import { mountDocs } from "./docs";
import { mountHome } from "./home";
import { mountIntegrations } from "./integrations";

mountApp(
  {
    "": () => ({ mount: (el) => mountHome(el) }),
    docs: { view: () => ({ mount: (el) => mountDocs(el) }), chrome: false },
    learnings: { view: () => ({ mount: (el) => mountDocs(el) }), chrome: false },
    discover: () => ({ mount: (el) => mountDiscover(el) }),
    integrations: () => ({ mount: (el) => mountIntegrations(el) }),
    apps: () => ({ mount: (el) => mountApps(el) }),
  },
  {
    title: "brain",
    nav: [
      { label: "apps", href: "#apps", ariaLabel: "Apps on the brain platform" },
      { label: "integrations", href: "#integrations", ariaLabel: "Connect outside sources" },
      { label: "docs", href: "#docs", ariaLabel: "How the brain works" },
    ],
  },
);

registerSW();
