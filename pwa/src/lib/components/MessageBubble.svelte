<script lang="ts">
  import { marked } from 'marked';
  import type { ChatMessage } from '$lib/types';
  import ToolCallCard from './ToolCallCard.svelte';

  let { message }: { message: ChatMessage } = $props();

  marked.setOptions({ gfm: true, breaks: true });

  let rendered = $derived(
    message.role === 'assistant' && typeof message.content === 'string'
      ? marked.parse(message.content)
      : ''
  );
</script>

<article class="bubble role-{message.role}" aria-live={message.role === 'assistant' ? 'polite' : undefined}>
  {#if message.role === 'user'}
    <div class="text">{message.content}</div>
  {:else if typeof message.content === 'string'}
    <div class="prose">{@html rendered}</div>
  {:else}
    {#each message.content as block, i (i)}
      {#if block.type === 'text'}
        <div class="prose">{@html marked.parse(block.text)}</div>
      {:else if block.type === 'tool_use'}
        <ToolCallCard name={block.name} input={block.input} output={block.output} status={block.status} />
      {/if}
    {/each}
  {/if}
</article>

<style>
  .bubble {
    max-width: var(--conversation-max-width);
    margin: 0 auto;
    padding: var(--space-4) var(--space-4);
    animation: fade-in var(--duration-normal) var(--ease-out);
  }

  .role-user {
    text-align: right;
  }

  .role-user .text {
    display: inline-block;
    text-align: left;
    background: var(--color-bg-subtle);
    border-radius: var(--radius-lg);
    padding: var(--space-3) var(--space-4);
    max-width: 85%;
    white-space: pre-wrap;
    word-wrap: break-word;
  }

  .prose {
    line-height: var(--line-relaxed);
  }

  .prose :global(p) {
    margin: 0 0 var(--space-3);
  }

  .prose :global(p:last-child) {
    margin-bottom: 0;
  }

  .prose :global(code) {
    font-family: var(--font-mono);
    font-size: 0.9em;
    background: var(--color-bg-subtle);
    padding: 2px 6px;
    border-radius: var(--radius-sm);
  }

  .prose :global(pre) {
    background: var(--color-bg-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    overflow-x: auto;
  }

  .prose :global(pre code) {
    background: none;
    padding: 0;
  }

  .prose :global(ul),
  .prose :global(ol) {
    padding-left: var(--space-6);
  }

  @keyframes fade-in {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
</style>
