// The Integrations view (`#integrations`) — connect the brain to outside sources
// from the UI instead of editing env files. Today it manages the Notion
// integration token: GET /api/integrations reports whether Notion is connected
// and how ('db' = a token set here, 'env' = NOTION_TOKEN); PUT /api/integrations/
// notion {token} validates + stores a token; DELETE disconnects (falling back to
// the env token if one is set). The token is write-only from the browser's view —
// it's posted to the server and never read back.
//
// Roadmap: a one-click "Connect Notion" OAuth flow (pick pages right in Notion,
// no token to copy) replaces the paste step. Same stored-credential plumbing.

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
      <div class="disc-head"><h2>Integrations</h2></div>
      <p class="disc-sub">
        Connect the brain to outside sources. Credentials are managed here and
        stored by the brain — no env-file edits or restarts.
      </p>
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
    renderNotionCard(body, data.notion ?? {}, data.sync ?? {});
    appendLegibilityCard(body, data.legibility ?? {});
  } catch (err) {
    body.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(err)}).</p>`;
  }
}

// Whole minutes for the UI; the brain stores/serves seconds. 0 = off.
function toMinutes(seconds: number | undefined): number {
  return Math.max(0, Math.round((seconds ?? 0) / 60));
}

function renderNotionCard(body: HTMLElement, st: NotionStatus, sync: SyncStatus): void {
  const connected = !!st.connected;
  const viaEnv = connected && st.source === "env";
  const viaDb = connected && st.source === "db";

  const mins = toMinutes(sync.interval_seconds);
  const syncSource = sync.source === "db" ? "set here" : "from environment default";
  const syncState = mins === 0 ? "Off" : `Every ${mins} min`;
  // Reset only makes sense for a value stored here; an env default is the deployment's.
  const syncReset =
    sync.source === "db"
      ? `<button class="intg-sync-reset" type="button">Reset to default</button>`
      : "";

  const status = connected
    ? viaEnv
      ? `<span class="intg-dot is-on"></span> Connected via <code>NOTION_TOKEN</code> (environment). Paste a token below to manage it here instead.`
      : `<span class="intg-dot is-on"></span> Connected.`
    : `<span class="intg-dot is-off"></span> Not connected.`;

  // Disconnect only makes sense for a token we stored here; an env token is
  // owned by the deployment, not removable from the UI.
  const disconnect = viaDb
    ? `<button class="intg-disconnect" type="button">Disconnect</button>`
    : "";

  body.innerHTML = `
    <div class="intg-card">
      <div class="intg-card-head">
        <span class="intg-name">Notion</span>
        ${disconnect}
      </div>
      <p class="intg-status">${status}</p>
      <p class="intg-help">
        Create an internal integration at
        <a href="https://www.notion.so/profile/integrations" target="_blank" rel="noopener">notion.so/my-integrations</a>,
        copy its token, and share the pages you want with it. Then paste the token here.
      </p>
      <form class="intg-form">
        <input class="intg-token" type="password" autocomplete="off"
          placeholder="ntn_… or secret_…" aria-label="Notion integration token" />
        <button class="intg-save" type="submit">${connected ? "Replace token" : "Connect"}</button>
      </form>
      <p class="intg-msg" role="status"></p>
      <div class="intg-sync">
        <span class="intg-sync-name">Auto-sync</span>
        <p class="intg-help">
          The brain re-pulls changed Notion pages on a timer. Set the interval in
          minutes — <strong>0 turns it off</strong>. Currently: ${esc(syncState)} (${syncSource}).
        </p>
        <form class="intg-sync-form">
          <input class="intg-sync-mins" type="number" min="0" step="1" inputmode="numeric"
            value="${mins}" aria-label="Auto-sync interval in minutes" />
          <span class="intg-sync-unit">min</span>
          <button class="intg-sync-save" type="submit">Save</button>
          ${syncReset}
        </form>
        <p class="intg-sync-msg" role="status"></p>
      </div>
      <p class="intg-roadmap">
        Coming soon: one-click <strong>Connect Notion</strong> — pick pages right
        in Notion, no token to copy.
      </p>
    </div>`;

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

  const syncForm = body.querySelector<HTMLFormElement>(".intg-sync-form")!;
  const syncMins = body.querySelector<HTMLInputElement>(".intg-sync-mins")!;
  const syncSave = body.querySelector<HTMLButtonElement>(".intg-sync-save")!;
  const syncMsg = body.querySelector<HTMLElement>(".intg-sync-msg")!;
  syncForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const m = Number(syncMins.value);
    if (!Number.isInteger(m) || m < 0) {
      syncMsg.textContent = "Enter a whole number of minutes (0 to turn off).";
      return;
    }
    void saveSync(body, syncSave, syncMsg, m * 60);
  });

  const syncResetBtn = body.querySelector<HTMLButtonElement>(".intg-sync-reset");
  syncResetBtn?.addEventListener("click", () => void resetSync(body, syncResetBtn, syncMsg));
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
    // Re-fetch so the card reflects the stored value + Reset option.
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
      btn.textContent = "Reset to default";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-sync-msg")!.textContent =
      "Reset to the environment default.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Reset to default";
    msg.textContent = String(err);
  }
}

async function connect(
  body: HTMLElement,
  save: HTMLButtonElement,
  msg: HTMLElement,
  token: string,
): Promise<void> {
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
      save.textContent = "Connect";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    // Re-fetch status so the card reflects the new 'db' source + Disconnect.
    await loadStatus(body);
    const where = data.workspace ? ` to ${data.workspace}` : "";
    body.querySelector<HTMLElement>(".intg-msg")!.textContent = `Connected${where}.`;
  } catch (err) {
    save.disabled = false;
    save.textContent = "Connect";
    msg.textContent = String(err);
  }
}

async function disconnect_(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Disconnecting…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/integrations/notion`, { method: "DELETE" });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = "Disconnect";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-msg")!.textContent = "Disconnected.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Disconnect";
    msg.textContent = String(err);
  }
}

// ---- Note-legibility settings card (mirrors the auto-sync card) ---------------
// Appended after the Notion card. The on/off toggle + knobs are runtime settings;
// the Anthropic API key is its own stored credential, set here like the Notion
// token (or supplied via the ANTHROPIC_API_KEY env).

function appendLegibilityCard(body: HTMLElement, leg: LegibilityStatus): void {
  const enabled = !!leg.enabled;
  const active = !!leg.active;
  const mode = leg.mode === "manual" ? "manual" : "auto";
  const threshold = typeof leg.threshold === "number" ? leg.threshold : 60;
  const hasKey = !!leg.has_key;
  const keyViaEnv = hasKey && leg.key_source === "env";
  const keyViaDb = hasKey && leg.key_source === "db";

  const status = !enabled
    ? `<span class="intg-dot is-off"></span> Off — notes are chunked exactly as written.`
    : active
      ? `<span class="intg-dot is-on"></span> On and running (${esc(mode)} mode).`
      : `<span class="intg-dot is-off"></span> On, but no Anthropic API key is set — ingesting as pass-through until you add one below.`;

  // How the key is provided, shown under the key form.
  const keyStatus = !hasKey
    ? `<span class="intg-dot is-off"></span> No Anthropic API key set.`
    : keyViaEnv
      ? `<span class="intg-dot is-on"></span> Key set via <code>ANTHROPIC_API_KEY</code> (environment). Paste a key below to manage it here instead.`
      : `<span class="intg-dot is-on"></span> Key set here.`;
  // Remove only makes sense for a key we stored here; an env key is the deployment's.
  const keyRemove = keyViaDb
    ? `<button class="intg-key-remove" type="button">Remove key</button>`
    : "";

  body.insertAdjacentHTML(
    "beforeend",
    `
    <div class="intg-card intg-legibility">
      <div class="intg-card-head"><span class="intg-name">Note legibility</span></div>
      <p class="intg-status">${status}</p>
      <p class="intg-help">
        An optional pass that restructures messy notes into self-describing
        sections the brain can recall well — <strong>your original is never
        changed and Notion is never written to</strong>. See
        <a href="#docs">writing legible notes</a>.
      </p>
      <div class="intg-key">
        <span class="intg-key-name">Anthropic API key</span>
        <p class="intg-help">${keyStatus}</p>
        <p class="intg-help">
          Get a key at
          <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>.
          It's stored by the brain and used only for this pass — never returned to the browser.
        </p>
        <form class="intg-key-form">
          <input class="intg-key-input" type="password" autocomplete="off"
            placeholder="sk-ant-…" aria-label="Anthropic API key" />
          <button class="intg-key-save" type="submit">${hasKey ? "Replace key" : "Save key"}</button>
          ${keyRemove}
        </form>
        <p class="intg-key-msg" role="status"></p>
      </div>
      <form class="intg-leg-form">
        <label class="intg-leg-row">
          <input class="intg-leg-enabled" type="checkbox" ${enabled ? "checked" : ""} /> Enable
        </label>
        <label class="intg-leg-row">
          Mode
          <select class="intg-leg-mode">
            <option value="auto" ${mode === "auto" ? "selected" : ""}>auto — rewrite low-health pages</option>
            <option value="manual" ${mode === "manual" ? "selected" : ""}>manual — health only; rewrite on request</option>
          </select>
        </label>
        <label class="intg-leg-row">
          Threshold
          <input class="intg-leg-threshold" type="number" min="0" max="100" step="1"
            inputmode="numeric" value="${threshold}" aria-label="Auto-rewrite health threshold" />
        </label>
        <button class="intg-leg-save" type="submit">Save</button>
        <button class="intg-leg-reset" type="button">Reset to default</button>
      </form>
      <p class="intg-leg-msg" role="status"></p>
    </div>`,
  );

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

  const keyForm = body.querySelector<HTMLFormElement>(".intg-key-form")!;
  const keyInput = body.querySelector<HTMLInputElement>(".intg-key-input")!;
  const keySave = body.querySelector<HTMLButtonElement>(".intg-key-save")!;
  const keyMsg = body.querySelector<HTMLElement>(".intg-key-msg")!;
  keyForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const key = keyInput.value.trim();
    if (!key) {
      keyMsg.textContent = "Enter a key first.";
      return;
    }
    void saveAnthropicKey(body, keySave, keyMsg, key);
  });
  const keyRemoveBtn = body.querySelector<HTMLButtonElement>(".intg-key-remove");
  keyRemoveBtn?.addEventListener("click", () => void removeAnthropicKey(body, keyRemoveBtn, keyMsg));
}

async function saveAnthropicKey(
  body: HTMLElement,
  btn: HTMLButtonElement,
  msg: HTMLElement,
  key: string,
): Promise<void> {
  const label = btn.textContent ?? "Save key";
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
    body.querySelector<HTMLElement>(".intg-key-msg")!.textContent = "Anthropic API key saved.";
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
      btn.textContent = "Remove key";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-key-msg")!.textContent = "Anthropic API key removed.";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Remove key";
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
      btn.textContent = "Reset to default";
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    await loadStatus(body);
    body.querySelector<HTMLElement>(".intg-leg-msg")!.textContent = "Reset to default (off).";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Reset to default";
    msg.textContent = String(err);
  }
}
