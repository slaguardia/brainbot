<script lang="ts">
  // Explore tab — force-directed graph viz placeholder.
  // Lib choice (D2): react-force-graph or cytoscape, decided when we ship.
  // Deferred until phase 1 migration populates the graph with real data.
</script>

<svelte:head>
  <title>Explore · Brainbot</title>
</svelte:head>

<section class="page">
  <header>
    <h1>Explore</h1>
    <p>Force-directed view of your graph.</p>
  </header>

  <div class="placeholder">
    <p>
      The mind-map view comes online after phase 1 populates the graph. Backend is
      ready (<code>/api/graph/neighborhood</code>), library not yet chosen.
    </p>
    <p class="hint">
      See <code>plans/phase-2-decisions.md</code> §D2 for the library shortlist.
    </p>
  </div>
</section>

<style>
  .page {
    max-width: var(--conversation-max-width);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
  }

  header h1 {
    margin: 0 0 var(--space-1);
    font-size: var(--text-2xl);
  }

  header p {
    color: var(--color-text-muted);
    margin: 0 0 var(--space-6);
  }

  .placeholder {
    padding: var(--space-6);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-md);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    text-align: center;
  }

  .placeholder p {
    margin: 0 0 var(--space-3);
  }

  .placeholder p:last-child {
    margin-bottom: 0;
  }

  .hint {
    font-size: var(--text-xs);
  }
</style>
