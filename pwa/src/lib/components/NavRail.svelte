<script lang="ts">
  // Bottom tab bar on phone; left rail on desktop.
  // Three primary destinations + admin (D1).

  let { current }: { current: string } = $props();

  const tabs = [
    { href: '/', label: 'Chat', icon: '💬' },
    { href: '/entity', label: 'Entities', icon: '🗂' },
    { href: '/explore', label: 'Explore', icon: '✦' },
    { href: '/admin', label: 'Admin', icon: '⚙' }
  ];

  function isActive(href: string): boolean {
    if (href === '/') return current === '/';
    return current.startsWith(href);
  }
</script>

<nav class="rail" aria-label="Primary">
  {#each tabs as tab}
    <a
      href={tab.href}
      class="tab"
      class:active={isActive(tab.href)}
      aria-current={isActive(tab.href) ? 'page' : undefined}
    >
      <span class="icon" aria-hidden="true">{tab.icon}</span>
      <span class="label">{tab.label}</span>
    </a>
  {/each}
</nav>

<style>
  .rail {
    grid-row: 2;
    display: flex;
    flex-direction: row;
    justify-content: space-around;
    align-items: stretch;
    background: var(--color-bg-elevated);
    border-top: 1px solid var(--color-border);
    padding-bottom: var(--safe-bottom);
  }

  .tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: var(--space-2) 0;
    min-width: 0;
    color: var(--color-text-muted);
    transition: color var(--duration-fast) var(--ease-out);
  }

  .tab.active {
    color: var(--color-accent);
  }

  .icon {
    font-size: var(--text-lg);
  }

  .label {
    font-size: var(--text-xs);
    font-weight: 500;
  }

  @media (min-width: 768px) {
    .rail {
      grid-column: 1;
      grid-row: 1;
      flex-direction: column;
      justify-content: flex-start;
      align-items: stretch;
      border-top: none;
      border-right: 1px solid var(--color-border);
      padding: var(--space-6) var(--space-3);
      padding-top: calc(var(--space-6) + var(--safe-top));
      gap: var(--space-1);
    }

    .tab {
      flex: 0;
      flex-direction: row;
      justify-content: flex-start;
      gap: var(--space-3);
      padding: var(--space-3) var(--space-4);
      border-radius: var(--radius-md);
      min-height: 44px;
    }

    .tab.active {
      background: var(--color-accent-subtle);
    }

    .icon {
      font-size: var(--text-base);
    }

    .label {
      font-size: var(--text-sm);
    }
  }
</style>
