<script lang="ts">
  // Bottom-anchored, auto-growing textarea. Uses a real <textarea> so iOS
  // keyboard dictation "just works" (D6 Tier 0). Enter submits; Shift+Enter
  // inserts newline. Cmd+/ from anywhere focuses this (handled in +page.svelte).

  type Props = {
    value: string;
    placeholder?: string;
    disabled?: boolean;
    onsubmit: (text: string) => void;
  };

  let {
    value = $bindable(''),
    placeholder = 'Message your brain…',
    disabled = false,
    onsubmit
  }: Props = $props();

  let textareaEl: HTMLTextAreaElement;

  export function focus() {
    textareaEl?.focus();
  }

  function autosize() {
    if (!textareaEl) return;
    textareaEl.style.height = 'auto';
    const max = 200;
    textareaEl.style.height = Math.min(textareaEl.scrollHeight, max) + 'px';
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onsubmit(text);
    value = '';
    queueMicrotask(autosize);
  }

  $effect(() => {
    void value;
    autosize();
  });
</script>

<form
  class="composer"
  onsubmit={(e) => {
    e.preventDefault();
    submit();
  }}
>
  <textarea
    bind:this={textareaEl}
    bind:value
    {placeholder}
    {disabled}
    rows="1"
    autocomplete="off"
    autocapitalize="sentences"
    spellcheck="true"
    enterkeyhint="send"
    onkeydown={handleKeydown}
    aria-label="Message"
  ></textarea>
  <button
    type="submit"
    class="send"
    disabled={disabled || !value.trim()}
    aria-label="Send message"
  >
    ↑
  </button>
</form>

<style>
  .composer {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
    padding: var(--space-3);
    margin: 0 auto;
    width: 100%;
    max-width: var(--composer-max-width);
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-md);
    transition:
      border-color var(--duration-fast) var(--ease-out),
      box-shadow var(--duration-fast) var(--ease-out);
  }

  .composer:focus-within {
    border-color: var(--color-accent);
  }

  textarea {
    flex: 1;
    min-height: 28px;
    max-height: 200px;
    padding: var(--space-2) var(--space-3);
    font-size: var(--text-base);
    line-height: var(--line-normal);
    outline: none;
    overflow-y: auto;
  }

  .send {
    flex: 0 0 auto;
    width: 36px;
    height: 36px;
    min-width: 36px;
    min-height: 36px;
    border-radius: var(--radius-full);
    background: var(--color-accent);
    color: var(--color-accent-fg);
    font-size: var(--text-lg);
    font-weight: 600;
    transition:
      transform var(--duration-fast) var(--ease-out),
      opacity var(--duration-fast) var(--ease-out);
  }

  .send:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .send:not(:disabled):active {
    transform: scale(0.95);
  }
</style>
