<script lang="ts">
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  function fmtCost(n: number): string {
    return `$${n.toFixed(4)}`;
  }

  function fmtMs(n: number): string {
    return `${n.toFixed(0)}ms`;
  }
</script>

<svelte:head>
  <title>Admin · Brainbot</title>
</svelte:head>

<section class="page">
  <header>
    <h1>Admin</h1>
    <p>Tool calls, cost, and errors — last 7 days.</p>
  </header>

  {#if !data.connected}
    <div class="placeholder">
      <p>
        Postgres is not reachable. Once the database is up and the migrations have run,
        this page populates from the <code>brain.tool_calls</code> table.
      </p>
    </div>
  {:else}
    <div class="cards">
      <div class="card">
        <span class="label">Total calls</span>
        <span class="value">{data.totalCalls}</span>
      </div>
      <div class="card">
        <span class="label">Total cost</span>
        <span class="value">{fmtCost(data.totalCost)}</span>
      </div>
      <div class="card" class:warn={data.errorRate > 0.05}>
        <span class="label">Error rate</span>
        <span class="value">{(data.errorRate * 100).toFixed(1)}%</span>
      </div>
    </div>

    <h2>By tool</h2>
    <table>
      <thead>
        <tr>
          <th scope="col">Tool</th>
          <th scope="col">Count</th>
          <th scope="col">p50</th>
          <th scope="col">p99</th>
          <th scope="col">Errors</th>
        </tr>
      </thead>
      <tbody>
        {#each data.byTool as row (row.name)}
          <tr>
            <td><code>{row.name}</code></td>
            <td>{row.count}</td>
            <td>{fmtMs(row.p50)}</td>
            <td>{fmtMs(row.p99)}</td>
            <td>{row.errors}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    <h2>Recent activity</h2>
    <table>
      <thead>
        <tr>
          <th scope="col">When</th>
          <th scope="col">Tool</th>
          <th scope="col">Status</th>
          <th scope="col">Latency</th>
          <th scope="col">Cost</th>
        </tr>
      </thead>
      <tbody>
        {#each data.recent as row (row.id)}
          <tr>
            <td>{new Date(row.occurredAt).toLocaleString()}</td>
            <td><code>{row.toolName}</code></td>
            <td><span class="status status-{row.status}">{row.status}</span></td>
            <td>{fmtMs(row.latencyMs)}</td>
            <td>{row.costUsd ? fmtCost(row.costUsd) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .page {
    max-width: 960px;
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

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
    margin-bottom: var(--space-8);
  }

  .card {
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elevated);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .card.warn {
    border-color: var(--color-danger);
  }

  .label {
    font-size: var(--text-xs);
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .value {
    font-size: var(--text-2xl);
    font-weight: 600;
  }

  h2 {
    font-size: var(--text-lg);
    margin: var(--space-6) 0 var(--space-3);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }

  th,
  td {
    text-align: left;
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
  }

  th {
    color: var(--color-text-muted);
    font-weight: 500;
  }

  .status {
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
  }

  .status-success {
    background: var(--color-bg-subtle);
    color: var(--color-success);
  }

  .status-error {
    background: var(--color-bg-subtle);
    color: var(--color-danger);
  }

  .placeholder {
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-md);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }
</style>
