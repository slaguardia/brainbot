// Smoke consumer: imports EVERY toolkit module, renders the shell with the
// palette applied, and exercises a component + the manifest/SW/brain/session
// surfaces. This is the end-to-end proof that the package is consumable. It is
// throwaway — not wired to a real backend, so the brain/session calls are made
// inside the (un-mounted) detail route only to prove the imports resolve and
// type-check.
import "@brainbot/web-toolkit/base.css";
import "@brainbot/web-toolkit/components.css";
import { tokens, cssVar } from "@brainbot/web-toolkit/tokens";
import { mountApp, setLoading, setEmpty, setError } from "@brainbot/web-toolkit/shell";
import type { View } from "@brainbot/web-toolkit/shell";
import { button, card, table, modal, progress, streamInto } from "@brainbot/web-toolkit/components";
import { manifest, registerSW } from "@brainbot/web-toolkit/pwa";
import { recall, doc, map } from "@brainbot/web-toolkit/brain";
import type { Chunk, Doc, Source } from "@brainbot/web-toolkit/brain";
import { currentUser } from "@brainbot/web-toolkit/session";

// pwa: build-time manifest (logged so the import is not tree-shaken away).
const mf = manifest({ name: "Smoke", short_name: "Smoke", description: "toolkit smoke test" });
console.log("manifest theme:", mf.theme_color);

// pwa: SW registration (no-ops/self-heals on localhost).
registerSW();

// tokens: prove the typed record + cssVar helper.
console.log("fg-muted var:", cssVar(tokens.fgMuted));

// home: render every component primitive so the palette is visibly applied.
const HomeView = (): View => ({
  mount(el) {
    const c = card({ title: "web-toolkit smoke", body: "every module imported and rendered." });

    const btn = button({ label: "open a modal", variant: "primary", onClick: () => m.open() });
    const accent = button({ label: "accent", variant: "accent" });
    const plain = button({ label: "default" });

    const t = table({
      columns: ["module", "status"],
      rows: [
        ["base.css", "imported"],
        ["components", "rendered"],
        ["brain", "wired"],
      ],
      onRowClick: (i) => console.log("row", i),
    });

    const m = modal({
      title: "smoke modal",
      body: "the modal primitive, harvested from scout.",
      actions: [button({ label: "ok", variant: "primary", onClick: () => m.close() })],
    });

    const p = progress({ title: "demo", onCancel: () => console.log("cancel") });

    el.append(c, btn, accent, plain, t);
    void p; // attached to body; referenced so the import is exercised.
  },
});

// detail: exercises the brain + session + state-helper imports. Not navigated to
// in the smoke run (no backend), but the factory is registered so its module
// graph is bundled and type-checked.
const DetailView = (): View => ({
  async mount(el) {
    setLoading(el, "loading…");
    try {
      const me = await currentUser();
      const sources: Source[] = await map();
      const hits: Chunk[] = await recall("hello", 5);
      const d: Doc | null = sources[0] ? await doc(sources[0].id) : null;
      if (!hits.length) setEmpty(el, `no results (user: ${me?.email ?? "anon"}, doc: ${d?.title ?? "none"})`);
    } catch (e) {
      setError(el, String(e));
    }
  },
});

// shell: render the chrome + hash router with the palette applied.
mountApp(
  { "": HomeView, detail: DetailView },
  { title: "smoke", nav: [{ label: "detail", href: "#detail" }] },
);

// keep streamInto referenced (SSE primitive) without opening a connection.
void streamInto;
