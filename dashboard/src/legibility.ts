// The per-source note-legibility view (`#legibility/<id>`) — the owner's audit
// surface for one source. It reads GET /api/sources/{id}/rewrite (the stored
// columns) and shows:
//   • health: the score, four sub-dimensions, and the actionable reasons (notes)
//   • a raw-vs-rewrite diff (the original you wrote, beside the restructured
//     version the brain chunks) — your original is never changed
//   • actions: "Rewrite now" (POST .../rewrite) and the per-source policy pin
//     (PUT .../rewrite-policy; 'off' pins to the raw voice)
//
// All brain-returned strings are escaped before they touch innerHTML.

import type { Health } from "@brainbot/web-toolkit/brain";

interface RewriteRecord {
  id: string;
  title: string | null;
  raw_text: string;
  rewrite_text: string | null;
  health: Health | null;
  rewrite_policy: "auto" | "off" | "manual";
}

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function mountLegibility(container: HTMLElement): void {
  const id = decodeURIComponent(location.hash.replace(/^#legibility\/?/, ""));
  if (!/^[0-9a-fA-F-]{36}$/.test(id)) {
    container.innerHTML = `<section class="home leg-view"><p class="home-status">No source selected — open a source's score badge from the <a href="#">home map</a>.</p></section>`;
    return;
  }
  container.innerHTML = `<section class="home leg-view"><p class="home-status">Loading legibility…</p></section>`;
  void load(container, id);
}

async function load(container: HTMLElement, id: string): Promise<void> {
  try {
    const res = await fetch(`/api/sources/${id}/rewrite`);
    const data = (await res.json()) as RewriteRecord & { error?: string };
    if (!res.ok) {
      container.innerHTML = `<section class="home leg-view"><p class="home-status">Couldn't load this source: ${esc(data.error ?? `HTTP ${res.status}`)}</p></section>`;
      return;
    }
    render(container, data);
  } catch (err) {
    container.innerHTML = `<section class="home leg-view"><p class="home-status">Couldn't reach the brain (${esc(err)}).</p></section>`;
  }
}

function healthBlock(health: Health | null): string {
  if (!health) {
    return `<p class="leg-help">Not analyzed yet. Enable note legibility in <a href="#integrations">integrations</a>, or use “Rewrite now” below.</p>`;
  }
  const score = Math.round(health.score);
  const tier = score >= 70 ? "good" : score >= 40 ? "fair" : "poor";
  const dims = health.dimensions;
  const dimRow = (label: string, v: number): string =>
    `<li><span class="leg-dim-name">${esc(label)}</span><span class="leg-dim-val">${Math.round(v * 100)}%</span></li>`;
  const reasons = health.notes.length
    ? `<ul class="leg-notes">${health.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`
    : `<p class="leg-help">No issues flagged — already legible to agents.</p>`;
  return `
    <div class="leg-health">
      <span class="src-health is-${tier} leg-score">${score}</span>
      <ul class="leg-dims">
        ${dimRow("separability", dims.separability)}
        ${dimRow("self-containment", dims.self_containment)}
        ${dimRow("redundancy", dims.redundancy)}
        ${dimRow("signal density", dims.signal_density)}
      </ul>
    </div>
    <div class="leg-reasons"><h3>Reasons</h3>${reasons}</div>`;
}

function render(container: HTMLElement, rec: RewriteRecord): void {
  const policy = rec.rewrite_policy;
  const opt = (v: string, label: string): string =>
    `<option value="${v}" ${policy === v ? "selected" : ""}>${esc(label)}</option>`;
  const rewriteCol = rec.rewrite_text
    ? `<pre class="leg-text">${esc(rec.rewrite_text)}</pre>`
    : `<p class="leg-help">No rewrite stored — this page is chunked from the raw text.</p>`;

  container.innerHTML = `
    <section class="home leg-view">
      <div class="disc-head"><h2>${esc(rec.title || "Untitled note")}</h2><a class="leg-back" href="#">← all sources</a></div>
      <p class="disc-sub">
        How legible this note is to your agents, and how the brain restructures it
        for retrieval. <strong>Your original is never changed and Notion is never
        written to.</strong> See <a href="#docs">writing legible notes</a>.
      </p>

      ${healthBlock(rec.health)}

      <div class="leg-actions">
        <button class="leg-rewrite" type="button">Rewrite now</button>
        <label class="leg-policy-row">
          Policy
          <select class="leg-policy tk-input">
            ${opt("auto", "auto — follow the global policy")}
            ${opt("manual", "manual — health only; rewrite on request")}
            ${opt("off", "off — pin to the raw voice (never rewrite)")}
          </select>
        </label>
        <span class="leg-msg" role="status"></span>
      </div>

      <div class="leg-diff">
        <div class="leg-col">
          <h3>Raw — what you wrote</h3>
          <pre class="leg-text">${esc(rec.raw_text)}</pre>
        </div>
        <div class="leg-col">
          <h3>Rewrite — what the brain chunks</h3>
          ${rewriteCol}
        </div>
      </div>
    </section>`;

  const id = rec.id;
  const msg = container.querySelector<HTMLElement>(".leg-msg")!;
  const rewriteBtn = container.querySelector<HTMLButtonElement>(".leg-rewrite")!;
  rewriteBtn.addEventListener("click", () => void rewriteNow(container, id, rewriteBtn, msg));
  const policySel = container.querySelector<HTMLSelectElement>(".leg-policy")!;
  policySel.addEventListener("change", () => void setPolicy(id, policySel.value, msg));
}

async function rewriteNow(
  container: HTMLElement,
  id: string,
  btn: HTMLButtonElement,
  msg: HTMLElement,
): Promise<void> {
  btn.disabled = true;
  btn.textContent = "Rewriting…";
  msg.textContent = "";
  try {
    const res = await fetch(`/api/sources/${id}/rewrite`, { method: "POST" });
    const data = (await res.json()) as { rewrote?: boolean; reason?: string; error?: string };
    if (!res.ok || data.rewrote === false) {
      btn.disabled = false;
      btn.textContent = "Rewrite now";
      msg.textContent = data.reason ?? data.error ?? `HTTP ${res.status}`;
      return;
    }
    await load(container, id); // re-render the fresh diff + health
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Rewrite now";
    msg.textContent = String(err);
  }
}

async function setPolicy(id: string, policy: string, msg: HTMLElement): Promise<void> {
  msg.textContent = "";
  try {
    const res = await fetch(`/api/sources/${id}/rewrite-policy`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy }),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) {
      msg.textContent = data.error ?? `HTTP ${res.status}`;
      return;
    }
    msg.textContent = policy === "off" ? "Pinned to the raw voice." : `Policy set to ${policy}.`;
  } catch (err) {
    msg.textContent = String(err);
  }
}
