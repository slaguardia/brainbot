<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import NavRail from '$lib/components/NavRail.svelte';

  let { children } = $props();
</script>

<div class="app-shell">
  <NavRail current={$page.url.pathname} />
  <main class="content">
    {@render children?.()}
  </main>
</div>

<style>
  .app-shell {
    display: grid;
    grid-template-columns: 1fr;
    grid-template-rows: 1fr auto;
    min-height: 100vh;
    min-height: 100dvh;
  }

  .content {
    grid-row: 1;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-top: var(--safe-top);
  }

  @media (min-width: 768px) {
    .app-shell {
      grid-template-columns: var(--sidebar-width) 1fr;
      grid-template-rows: 1fr;
    }
    .content {
      grid-column: 2;
      grid-row: 1;
    }
  }
</style>
