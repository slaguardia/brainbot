// The Integrations view (`#integrations`) — manage the brain's credentials and
// ingest settings from the UI instead of editing env files. Two groups:
//   • API keys      — the Notion token + Anthropic key the brain authenticates
//                     with. A value set here overrides its env var; it's stored by
//                     the brain and never read back to the browser.
//   • Brain settings — how the brain ingests: the Notion auto-sync interval and
//                     the optional note-legibility pass.
// Everything reads from GET /api/integrations; each card PUT/DELETEs its own
// endpoint and re-loads the status.

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

interface NotionStatus {
  connected?: boolean;
  source?: "db" | "env" | null;
}

interface SyncStatus {
  interval_seconds?: number;
  source?: "db" | "env";
}

interface LegibilityStatus {
  enabled?: boolean; // the stored toggle
  active?: boolean; // enabled AND the key is present (i.e. actually running)
  mode?: "auto" | "manual";
  threshold?: number;
  model?: string;
  has_key?: boolean;
  key_source?: "db" | "env" | null; // how the Anthropic key is provided
}

interface IntegrationsStatus {
  notion?: NotionStatus;
  sync?: SyncStatus;
  legibility?: LegibilityStatus;
}

export function mountIntegrations(container: HTMLElement): void {
  container.innerHTML = `
    <section class="home integrations">
      <header class="page-head">
        <h1 class="page-title">Integrations</h1>
        <p class="page-sub">
          Manage the brain's credentials and ingest settings here — stored by the
          brain, with no env-file edits or restarts.
        </p>
      </header>
      <div class="intg-body"><p class="home-status">Checking…</p></div>
    </section>`;
  const body = container.querySelector<HTMLElement>(".intg-body")!;
  void loadStatus(body);
}

async function loadStatus(body: HTMLElement): Promise<void> {
  try {
    const res = await fetch(`/api/integrations`);
    const data = (await res.json()) as IntegrationsStatus & { error?: string };
    if (!res.ok) {
      body.innerHTML = `<p class="home-status">Couldn't load integrations: ${esc(data.error ?? `HTTP ${res.status}`)}</p>`;
      return;
    }
    renderAll(body, data);
  } catch (err) {
    body.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(err)}).</p>`;
  }
}

function renderAll(body: HTMLElement, data: IntegrationsStatus): void {
  const notion = data.notion ?? {};
  const sync = data.sync ?? {};
  const leg = data.legibility ?? {};
  body.innerHTML = `
    <section class="intg-group">
      <div class="intg-group-head">
        <h3>API keys</h3>
        <p>
          Credentials the brain authenticates with. A value set here is stored by
          the brain, overrides its environment variable, and is never shown again.
        </p>
      </div>
      <div class="intg-grid">
        ${notionTokenCard(notion)}
        ${anthropicKeyCard(leg)}
      </div>
    </section>
    <section class="intg-group">
      <div class="intg-group-head">
        <h3>Brain settings</h3>
        <p>How the brain ingests from Notion. Changes apply live — no restart.</p>
      </div>
      <div class="intg-grid">
        ${syncCard(sync)}
        ${legibilityCard(leg)}
      </div>
    </section>`;
  wireNotion(body);
  wireAnthropic(body);
  wireSync(body);
  wireLegibility(body);
}

// Whole minutes for the UI; the brain stores/serves seconds. 0 = off.
function toMinutes(seconds: number | undefined): number {
  return Math.max(0, Math.round((seconds ?? 0) / 60));
}

// ---- API keys ---------------------------------------------------------------

function notionTokenCard(st: NotionStatus): string {
  const connected = !!st.connected;
  const viaEnv = connected && st.source === "env";
  const viaDb = connected && st.source === "db";

  const status = !connected
    ? `<span class="tk-badge">Not set</span>`
    : viaEnv
      ? `<span class="tk-badge tk-badge-yes">Set from environment</span>`
      : `<span class="tk-badge tk-badge-yes">Set here</span>`;
  // Remove only makes sense for a token stored here; an env token is the deployment's.
  const action = viaDb ? `<button class="intg-disconnect" type="button">Remove</button>` : "";

  return `
    <div class="intg-card">
      <div class="intg-card-head"><span class="intg-name">Notion token</span>${action}</div>
      <p class="intg-status">${status}</p>
      <p class="intg-help">
        Create an integration at
        <a href="https://www.notion.so/profile/integrations" target="_blank" rel="noopener">notion.so/my-integrations</a>,
        share your pages with it, then paste its token.
      </p>
      <form class="intg-form">
        <input class="intg-token tk-input" type="password" autocomplete="off"
          placeholder="ntn_… or secret_…" aria-label="Notion integration token" />
        <button class="intg-save" type="submit">${connected ? "Replace" : "Save"}</button>
      </form>
      <p class="intg-msg" role="status"></p>
    </div>`;
}

function wireNotion(body: HTMLElement): void {
  const form = body.querySelector<HTMLFormElement>(".intg-form")!;
  const input = body.querySelector<HTMLInputElement>(".intg-token")!;
  const save = body.querySelector<HTMLButtonElement>(".intg-save")!;
  const msg = body.querySelector<HTMLElement>(".intg-msg")!;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const token = input.value.trim();
    if (!token) {
      msg.textContent = "Enter a token first.";
      return;
    }
    void connect(body, save, msg, token);
  });
  const disc = body.querySelector<HTMLButtonElement>(".intg-disconnect");
  disc?.addEventListener("click", () => void disconnect_(body, disc, msg));
}

function anthropicKeyCard(leg: LegibilityStatus): string {
  const hasKey = !!leg.has_key;
  const viaEnv = hasKey && leg.key_source === "env";
  const viaDb = hasKey && leg.key_source === "db";

  const status = !hasKey
    ? `<span class="tk-badge">Not set</span>`
    : viaEnv
      ? `<span class="tk-badge tk-badge-yes">Set from environment</span>`
      : `<span class="tk-badge tk-badge-yes">Set here</span>`;
  const action = viaDb ? `<button class="intg-key-remove" type="button">Remove</button>` : "";

  return `
    <div class="intg-card">
      <div class="intg-card-head"><span class="intg-name">Anthropic key</span>${action}</div>
      <p class="intg-status">${status}</p>
      <p class="intg-help">
        Powers the optional <strong>Note legibility</strong> pass (below). Get a key at
        <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>.
      </p>
      <form class="intg-key-form">
        <input class="intg-key-input tk-input" type="password" autocomplete="off"
          placeholder="sk-ant-…" aria-label="Anthropic API key" />
        <button class="intg-key-save" type="submit">${hasKey ? "Replace" : "Save"}</button>
      </form>
      <p class="intg-key-msg" role="status"></p>
    </div>`;
}

function wireAnthropic(body: HTMLElement): void {
  const form = body.querySelector<HTMLFormElement>(".intg-key-form")!;
  const input = body.querySelector<HTMLInputElement>(".intg-key-input")!;
  const save = body.querySelector<HTMLButtonElement>(".intg-key-save")!;
  const msg = body.querySelector<HTMLElement>(".intg-key-msg")!;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const key = input.value.trim();
    if (!key) {
      msg.textContent = "Enter a key first.";
      return;
    }
    void saveAnthropicKey(body, save, msg, key);
  });
  const remove = body.querySelector<HTMLButtonElement>(".intg-key-remove");
  remove?.addEventListener("click", () => void removeAnthropicKey(body, remove, msg));
}

// ---- Brain settings ---------------------------------------------------------

function syncCard(sync: SyncStatus): string {
  const mins = toMinutes(sync.interval_seconds);
  const viaDb = sync.source === "db";
  const reset = viaDb ? `<button class="intg-sync-reset" type="button">Reset</button>` : "";
  const status =
    mins === 0
      ? `<span class="tk-badge">Off</span>`
      : `<span class="tk-badge tk-badge-yes">Every ${mins} min</span>`;
  const src = viaDb ? "" : ` <span class="intg-src">(default)</span>`;

  return `
    <div class="intg-card">
      <div class="intg-card-head"><span class="intg-name">Notion auto-sync</span></div>
      <p class="intg-status">${status}${src}</p>
      <p class="intg-help">
        The brain re-pulls changed Notion pages on a timer and picks up new pages
        added under anything you've already pulled. Interval in minutes —
        <strong>0 turns it off</strong>.
      </p>
      <form class="intg-sync-form">
        <input class="intg-sync-mins tk-input" type="number" min="0" step="1" inputmode="numeric"
          value="${mins}" aria-label="Auto-sync interval in minutes" />
        <span class="intg-sync-unit">min</span>
        <button class="intg-sync-save" type="submit">Save</button>
        ${reset}
      </form>
      <p class="intg-sync-msg" role="status"></p>
    </div>`;
}

function wireSync(body: HTMLElement): void {
  const form = body.querySelector<HTMLFormElement>(".intg-sync-form")!;
  const mins = body.querySelector<HTMLInputElement>(".intg-sync-mins")!;
  const save = body.querySelector<HTMLButtonElement>(".intg-sync-save")!;
  const msg = body.querySelector<HTMLElement>(".intg-sync-msg")!;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const m = Number(mins.value);
    if (!Number.isInteger(m) || m < 0) {
      msg.textContent = "Enter a whole number of minutes (0 to turn off).";
      return;
    }
    void saveSync(body, save, msg, m * 60);
  });
  const resetBtn = body.querySelector<HTMLButtonElement>(".intg-sync-reset");
  resetBtn?.addEventListener("click", () => void resetSync(body, resetBtn, msg));
}

function legibilityCard(leg: LegibilityStatus): string {
  const enabled = !!leg.enabled;
  const active = !!leg.active;
  const mode = leg.mode === "manual" ? "manual" : "auto";
  const threshold = typeof leg.threshold === "number" ? leg.threshold : 60;
  const hasKey = !!leg.has_key;

  const status = !enabled
    ? `<span class="tk-badge">Off</span>`
    : active
      ? `<span class="tk-badge tk-badge-yes">On (${esc(mode)})</span>`
      : `<span class="tk-badge tk-badge-maybe">On — needs an Anthropic key</span>`;
  // When enabled without a key, point at the API keys section above instead of
  // the generic blurb — that's the one thing the user needs to do.
  const help =
    enabled && !hasKey
      ? `Enabled, but no Anthropic key is set — add one under <strong>API keys</strong> above to activate it.`
      : `Restructures messy notes into self-describing sections for better recall —
         your original is never changed. <a href="#docs">Learn more</a>.`;

  return `
    <div class="intg-card">
      <div class="intg-card-head"><span class="intg-name">Note legibility</span></div>
      <p class="intg-status">${status}</p>
      <p class="intg-help">${help}</p>
      <form class="intg-leg-form">
        <label class="intg-leg-row">
          <input class="intg-leg-enabled" type="checkbox" ${enabled ? "checked" : ""} /> Enable
        </label>
        <label class="intg-leg-row">
          Mode
          <select class="intg-leg-mode tk-input">
            <option value="auto" ${mode === "auto" ? "selected" : ""}>auto — rewrite low-health pages</option>
            <option value="manual" ${mode === "manual" ? "selected" : ""}>manual — health only</option>
          </select>
        </label>
        <label class="intg-leg-row">
          Threshold
          <input class="intg-leg-threshold tk-input" type="number" min="0" max="100" step="1"
            inputmode="numeric" value="${threshold}" aria-label="Auto-rewrite health threshold" />
        </label>
        <div class="intg-leg-actions">
          <button class="intg-leg-save" type="submit">Save</button>
          <button class="intg-leg-reset" type="button">Reset</button>
        </div>
      </form>
      <p class="intg-leg-msg" role="status"></p>
    </div>`;
}

function wireLegibility(body: HTMLElement): void {
  const form = body.querySelector<HTMLFormElement>(".intg-leg-form")!;
  const enabledEl = body.querySelector<HTMLInputElement>(".intg-leg-enabled")!;
  const modeEl = body.querySelector<HTMLSelectElement>(".intg-leg-mode")!;
  const thrEl = body.querySelector<HTMLInputElement>(".intg-leg-threshold")!;
  const save = body.querySelector<HTMLButtonElement>(".intg-leg-save")!;
  const msg = body.querySelector<HTMLElement>(".intg-leg-msg")!;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const thr = Number(thrEl.value);
    if (!Number.isInteger(thr) || thr < 0 || thr > 100) {
      msg.textContent = "Threshold must be a whole number from 0 to 100.";
      return;
    }
    void saveLegibility(body, save, msg, {
      enabled: enabledEl.checked,
      mode: modeEl.value === "manual" ? "manual" : "auto",
      threshold: thr,
    });
  });
  const resetBtn = body.querySelector<HTMLButtonElement>(".intg-leg-reset")!;
  resetBtn.addEventListener("click", () => void resetLegibility(body, resetBtn, msg));
}

// ---- network handlers -------------------------------------------------------
// Each restores the button's own label on error (success re-renders via loadStatus).

async function connect(
  body: HTMLElement,
  save: HTMLButtonElement,
  msg: HTMLElement,
  token: string,
): Promise<void> {
  const label = save.textContent ?? "Save";
  save.disabled = true;
  save.textContent = "Connecting…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/notion`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = (await res.json()) as { workspace?: string; error?: string };
    if (!res.ok) {
      save.disabled = false;
      save.textContent = label;
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    const where = data.workspace ? ` to ${data.workspace}` : "";
    body.querySelector<HTMLElement>(".intg-msg")!.textContent = `Connected${where}.`;
  } catch (err) {
    save.disabled = false;
    save.textContent = label;
    msg.textContent = String(err);
  }
}

async function disconnect_(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Removing…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/notion`, { method: "DELETE" });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Remove";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-msg")!.textContent = "Removed.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Remove";
    msg.textContent = String(err);
  }
}

async function saveSync(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
  intervalSeconds: number,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Saving…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/notion/sync`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Save";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-sync-msg")!.textContent =
      intervalSeconds === 0 ? "Auto-sync turned off." : "Auto-sync updated.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Save";
    msg.textContent = String(err);
  }
}

async function resetSync(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Resetting…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/notion/sync`, { method: "DELETE" });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Reset";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-sync-msg")!.textContent =
      "Reset to the environment default.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Reset";
    msg.textContent = String(err);
  }
}

async function saveAnthropicKey(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
  key: string,
): Promise<void> {
  const label = btn.textContent ?? "Save";
  btn.disabled = true;
  btn.textContent = "Saving…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/anthropic`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = label;
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-key-msg")!.textContent = "Anthropic key saved.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = label;
    msg.textContent = String(err);
  }
}

async function removeAnthropicKey(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Removing…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/anthropic`, { method: "DELETE" });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Remove";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-key-msg")!.textContent = "Anthropic key removed.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Remove";
    msg.textContent = String(err);
  }
}

async function saveLegibility(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
  payload: { enabled: boolean; mode: "auto" | "manual"; threshold: number },
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Saving…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/legibility`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Save";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-leg-msg")!.textContent = "Legibility settings saved.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Save";
    msg.textContent = String(err);
  }
}

async function resetLegibility(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Resetting…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/legibility`, { method: "DELETE" });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Reset";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-leg-msg")!.textContent = "Reset to default (off).";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Reset";
    msg.textContent = String(err);
  }
}
