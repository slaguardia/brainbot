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

interface IntegrationsStatus {
  notion?: NotionStatus;
  sync?: SyncStatus;
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
