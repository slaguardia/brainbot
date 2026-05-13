<script lang="ts">
  // Tool-call surface inside an assistant message. Collapsed by default, with
  // a status dot and the tool name. Expands to show input/output JSON.

  type Props = {
    name: string;
    input?: unknown;
    output?: unknown;
    status: 'pending' | 'success' | 'error';
  };

  let { name, input, output, status }: Props = $props();
  let expanded = $state(false);

  function summary(): string {
    if (!input || typeof input !== 'object') return '';
    const obj = input as Record<string, unknown>;
    const key = Object.keys(obj)[0];
    if (!key) return '';
    const val = obj[key];
    const text = typeof val === 'string' ? val : JSON.stringify(val);
    return text.length > 60 ? text.slice(0, 60) + '…' : text;
  }
</script>

<div class="tool" data-status={status}>
  <button
    class="header"
    onclick={() => (expanded = !expanded)}
    aria-expanded={expanded}
    aria-label={`Tool call: ${name}, status: ${status}`}
  >
    <span class="dot" aria-hidden="true"></span>
    <span class="name">{name}</span>
    {#if summary()}
      <span class="summary">{summary()}</span>
    {/if}
    <span class="chevron" aria-hidden="true">{expanded ? '▾' : '▸'}</span>
  </button>
  {#if expanded}
    <div class="body">
      <details open>
        <summary>input</summary>
        <pre>{JSON.stringify(input, null, 2)}</pre>
      </details>
      {#if output !== undefined}
        <details open>
          <summary>output</summary>
          <pre>{JSON.stringify(output, null, 2)}</pre>
        </details>
      {/if}
    </div>
  {/if}
</div>

<style>
  .tool {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elevated);
    margin: var(--space-2) 0;
    overflow: hidden;
    font-size: var(--text-sm);
  }

  .header {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    min-height: 36px;
    text-align: left;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    flex: 0 0 auto;
  }

  [data-status='pending'] .dot {
    background: var(--color-text-muted);
    animation: pulse 1.4s infinite ease-in-out;
  }
  [data-status='success'] .dot {
    background: var(--color-success);
  }
  [data-status='error'] .dot {
    background: var(--color-danger);
  }

  .name {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--color-text);
    flex: 0 0 auto;
  }

  .summary {
    color: var(--color-text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .chevron {
    color: var(--color-text-muted);
    flex: 0 0 auto;
  }

  .body {
    border-top: 1px solid var(--color-border);
    padding: var(--space-3);
    background: var(--color-bg-subtle);
  }

  .body details + details {
    margin-top: var(--space-2);
  }

  pre {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    overflow-x: auto;
    margin: var(--space-2) 0 0;
    color: var(--color-text-muted);
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
