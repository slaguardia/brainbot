<script lang="ts">
  // Focused outreach workflow (D5 — secondary surface; chat is primary).
  // Real implementation calls draft_outreach tool via the chat harness.
</script>

<svelte:head>
  <title>Draft outreach · Brainbot</title>
</svelte:head>

<section class="page">
  <header>
    <h1>Draft outreach</h1>
    <p>Paste a company URL, LinkedIn, or just a name.</p>
  </header>

  <form class="form">
    <label>
      <span>Target</span>
      <input type="text" placeholder="e.g. anthropic.com or Anthropic" disabled />
    </label>
    <label>
      <span>Notes (optional)</span>
      <textarea rows="3" placeholder="Anything specific to weave in" disabled></textarea>
    </label>
    <button type="submit" disabled>Draft</button>
  </form>

  <div class="placeholder">
    <p>
      Wired but blocked on phase 1: this kicks off a chat-style flow with
      <code>draft_outreach</code> as the first tool call. The draft is editable inline,
      then saved via <code>save_draft</code> and promoted to a Graphiti episode when sent.
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

  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  label span {
    font-size: var(--text-sm);
    color: var(--color-text-muted);
  }

  input,
  textarea {
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elevated);
    font-size: var(--text-base);
  }

  button[type='submit'] {
    align-self: flex-start;
    padding: var(--space-3) var(--space-5);
    background: var(--color-accent);
    color: var(--color-accent-fg);
    border-radius: var(--radius-md);
    font-weight: 600;
  }

  button[type='submit']:disabled {
    opacity: 0.4;
    cursor: not-allowed;
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
