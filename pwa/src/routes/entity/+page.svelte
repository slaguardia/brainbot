<script lang="ts">
  // Entity index. Shows a search + recent entities list.
  // Real implementation needs a Graphiti `list_recent` or hybrid search call
  // — phase-1-blocked. Placeholder UI until then.
</script>

<svelte:head>
  <title>Entities · Brainbot</title>
</svelte:head>

<section class="page">
  <header>
    <h1>Entities</h1>
    <p>Companies, people, applications, outreach, and notes.</p>
  </header>

  <div class="search">
    <input type="search" placeholder="Search entities…" aria-label="Search entities" disabled />
  </div>

  <div class="placeholder">
    <p>
      Entity browsing is wired but the data source isn't online yet. Once phase 1 lands and
      the Graphiti REST endpoint is reachable, this list will populate from
      <code>/api/entities/recent</code>.
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

  .search input {
    width: 100%;
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elevated);
    font-size: var(--text-base);
  }

  .placeholder {
    margin-top: var(--space-6);
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-md);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
</style>
