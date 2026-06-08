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

interface IntegrationsStatus {
  notion?: NotionStatus;
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
    renderNotionCard(body, data.notion ?? {});
  } catch (err) {
    body.innerHTML = `<p class="home-status">Couldn't reach the brain (${esc(err)}).</p>`;
  }
}

function renderNotionCard(body: HTMLElement, st: NotionStatus): void {
  const connected = !!st.connected;
  const viaEnv = connected && st.source === "env";
  const viaDb = connected && st.source === "db";

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
