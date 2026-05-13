<script lang="ts">
  // Compact entity row used in lists. Tap = navigate to /entity/[id].

  type Props = {
    id: string;
    label: string;
    type: string;
    subtitle?: string;
  };

  let { id, label, type, subtitle }: Props = $props();
</script>

<a class="card" href={`/entity/${id}`}>
  <div class="head">
    <span class="type">{type}</span>
  </div>
  <div class="label">{label}</div>
  {#if subtitle}
    <div class="subtitle">{subtitle}</div>
  {/if}
</a>

<style>
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elevated);
    color: var(--color-text);
    min-height: 0;
    transition:
      border-color var(--duration-fast) var(--ease-out),
      box-shadow var(--duration-fast) var(--ease-out);
  }

  .card:hover {
    border-color: var(--color-border-strong);
    box-shadow: var(--shadow-sm);
    text-decoration: none;
  }

  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .type {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-transform: lowercase;
    color: var(--color-text-muted);
  }

  .label {
    font-size: var(--text-base);
    font-weight: 600;
  }

  .subtitle {
    font-size: var(--text-sm);
    color: var(--color-text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
