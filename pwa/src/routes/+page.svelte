<script lang="ts">
  import { onMount } from 'svelte';
  import Composer from '$lib/components/Composer.svelte';
  import MessageBubble from '$lib/components/MessageBubble.svelte';
  import type { ChatMessage } from '$lib/types';

  let messages = $state<ChatMessage[]>([]);
  let input = $state('');
  let streaming = $state(false);
  let composer: Composer | undefined = $state();
  let scroller: HTMLDivElement | undefined = $state();

  function uid(): string {
    return crypto.randomUUID();
  }

  function scrollToBottom() {
    queueMicrotask(() => {
      if (scroller) scroller.scrollTop = scroller.scrollHeight;
    });
  }

  async function send(text: string) {
    const userMsg: ChatMessage = {
      id: uid(),
      role: 'user',
      content: text,
      createdAt: new Date().toISOString()
    };
    messages = [...messages, userMsg];
    scrollToBottom();

    streaming = true;
    const assistantMsg: ChatMessage = {
      id: uid(),
      role: 'assistant',
      content: '',
      createdAt: new Date().toISOString()
    };
    messages = [...messages, assistantMsg];

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: messages
            .filter((m) => m.role !== 'system')
            .map((m) => ({ role: m.role, content: m.content }))
        })
      });

      if (!res.ok || !res.body) {
        const err = await res.text();
        assistantMsg.content = `*Error: ${err || res.statusText}*`;
        messages = [...messages];
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const events = buf.split('\n\n');
        buf = events.pop() ?? '';

        for (const event of events) {
          const line = event.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          const data = line.slice(6);
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data);
            if (parsed.delta) {
              assistantMsg.content = (assistantMsg.content as string) + parsed.delta;
              messages = [...messages];
              scrollToBottom();
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e) {
      assistantMsg.content = `*Connection error: ${String(e)}*`;
      messages = [...messages];
    } finally {
      streaming = false;
    }
  }

  onMount(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === '/') {
        e.preventDefault();
        composer?.focus();
      }
      if (mod && e.key === 'k') {
        e.preventDefault();
        messages = [];
        composer?.focus();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
</script>

<svelte:head>
  <title>Brainbot</title>
</svelte:head>

<div class="page">
  <div class="scroll" bind:this={scroller}>
    {#if messages.length === 0}
      <div class="empty">
        <h1>Brainbot</h1>
        <p>Ask anything. Drafts, recall, capture.</p>
        <div class="suggestions">
          <button onclick={() => send('Draft an outreach DM to the founder of a small AI startup')}>
            Draft outreach
          </button>
          <button onclick={() => send('What companies have I been tracking this week?')}>
            Tracker status
          </button>
          <button onclick={() => send('Capture this thought: …')}>Capture a thought</button>
        </div>
      </div>
    {:else}
      {#each messages as msg (msg.id)}
        <MessageBubble message={msg} />
      {/each}
    {/if}
  </div>
  <div class="dock">
    <Composer bind:this={composer} bind:value={input} disabled={streaming} onsubmit={send} />
  </div>
</div>

<style>
  .page {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 100dvh;
  }

  .scroll {
    flex: 1;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: var(--space-4) 0 var(--space-6);
  }

  .empty {
    max-width: var(--conversation-max-width);
    margin: 0 auto;
    padding: var(--space-12) var(--space-4);
    text-align: center;
  }

  .empty h1 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-2xl);
    font-weight: 600;
  }

  .empty p {
    color: var(--color-text-muted);
    margin: 0 0 var(--space-6);
  }

  .suggestions {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    align-items: stretch;
  }

  .suggestions button {
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elevated);
    color: var(--color-text);
    font-size: var(--text-sm);
    text-align: left;
    transition: border-color var(--duration-fast) var(--ease-out);
  }

  .suggestions button:hover {
    border-color: var(--color-accent);
  }

  .dock {
    padding: var(--space-3) var(--space-3) calc(var(--space-3) + var(--safe-bottom));
    background: linear-gradient(to top, var(--color-bg) 70%, transparent);
  }

  @media (min-width: 768px) {
    .suggestions {
      flex-direction: row;
      flex-wrap: wrap;
      justify-content: center;
    }
    .suggestions button {
      flex: 0 0 auto;
    }
  }
</style>
