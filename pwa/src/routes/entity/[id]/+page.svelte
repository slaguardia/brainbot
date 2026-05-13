<script lang="ts">
  import EntityCard from '$lib/components/EntityCard.svelte';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
</script>

<svelte:head>
  <title>{data.entity?.label ?? 'Entity'} · Brainbot</title>
</svelte:head>

<section class="page">
  {#if !data.entity}
    <div class="placeholder">
      <p>Entity not found, or phase 1 not online.</p>
    </div>
  {:else}
    <header>
      <span class="type">{data.entity.type}</span>
      <h1>{data.entity.label}</h1>
    </header>

    {#if data.entity.neighbors.length === 0}
      <p class="muted">No connections yet.</p>
    {:else}
      <div class="grid">
        {#each data.entity.neighbors as n (n.id)}
          <EntityCard id={n.id} label={n.label} type={n.type} subtitle={n.via} />
        {/each}
      </div>
    {/if}
  {/if}
</section>

<style>
  .page {
    max-width: var(--conversation-max-width);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
  }

  header {
    margin-bottom: var(--space-6);
  }

  .type {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }

  h1 {
    margin: var(--space-1) 0 0;
    font-size: var(--text-2xl);
  }

  .grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--space-3);
  }

  @media (min-width: 600px) {
    .grid {
      grid-template-columns: 1fr 1fr;
    }
  }

  .muted {
    color: var(--color-text-muted);
  }

  .placeholder {
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-md);
    color: var(--color-text-muted);
  }
</style>
