<script lang="ts">
  // Slide-in conversation list. Triggered from the chat page header.
  // On phone: full-width sheet from the left. On desktop: 320px sidebar.

  import type { Conversation } from '$lib/types';

  type Props = {
    open: boolean;
    conversations: Conversation[];
    currentId: string | null;
    onclose: () => void;
    onselect: (id: string) => void;
    onnew: () => void;
  };

  let { open, conversations, currentId, onclose, onselect, onnew }: Props = $props();

  function fmtRelative(iso: string): string {
    const d = new Date(iso);
    const now = Date.now();
    const ms = now - d.getTime();
    const min = 60_000;
    const hour = 60 * min;
    const day = 24 * hour;
    if (ms < hour) return `${Math.max(1, Math.floor(ms / min))}m`;
    if (ms < day) return `${Math.floor(ms / hour)}h`;
    if (ms < 7 * day) return `${Math.floor(ms / day)}d`;
    return d.toLocaleDateString();
  }
</script>

{#if open}
  <button
    type="button"
    class="scrim"
    onclick={onclose}
    aria-label="Close conversations"
  ></button>
{/if}

<aside class="drawer" class:open aria-hidden={!open}>
  <header>
    <h2>Conversations</h2>
    <button class="new" onclick={onnew} aria-label="New conversation">+ New</button>
  </header>
  <ul>
    {#each conversations as conv (conv.id)}
      <li>
        <button
          class="row"
          class:active={conv.id === currentId}
          onclick={() => onselect(conv.id)}
          aria-current={conv.id === currentId ? 'page' : undefined}
        >
          <span class="title">{conv.title}</span>
          <span class="when">{fmtRelative(conv.updatedAt)}</span>
        </button>
      </li>
    {/each}
    {#if conversations.length === 0}
      <li class="empty">No conversations yet.</li>
    {/if}
  </ul>
</aside>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    z-index: 10;
    border: none;
    padding: 0;
    width: 100%;
    height: 100%;
    min-height: 0;
    min-width: 0;
    cursor: pointer;
    animation: fade-in var(--duration-normal) var(--ease-out);
  }

  .drawer {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    width: min(320px, 100vw);
    background: var(--color-bg-elevated);
    border-right: 1px solid var(--color-border);
    z-index: 11;
    display: flex;
    flex-direction: column;
    transform: translateX(-100%);
    transition: transform var(--duration-normal) var(--ease-out);
    padding-top: var(--safe-top);
    padding-bottom: var(--safe-bottom);
  }

  .drawer.open {
    transform: translateX(0);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }

  h2 {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 600;
  }

  .new {
    font-size: var(--text-sm);
    color: var(--color-accent);
    font-weight: 500;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
  }

  .new:hover {
    background: var(--color-accent-subtle);
  }

  ul {
    list-style: none;
    margin: 0;
    padding: var(--space-2);
    overflow-y: auto;
    flex: 1;
  }

  li {
    margin: 0;
  }

  .row {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-sm);
    text-align: left;
    color: var(--color-text);
    min-height: 44px;
  }

  .row:hover {
    background: var(--color-bg-subtle);
  }

  .row.active {
    background: var(--color-accent-subtle);
    color: var(--color-accent);
  }

  .title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-sm);
  }

  .when {
    flex: 0 0 auto;
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }

  .empty {
    padding: var(--space-4);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    text-align: center;
  }

  @keyframes fade-in {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
</style>
