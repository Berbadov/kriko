<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { ButtonVariant } from './lib/types';

  interface Props {
    variant?: ButtonVariant;
    wide?: boolean;
    type?: 'button' | 'submit';
    disabled?: boolean;
    pressed?: boolean;
    /** Content of the `.k-tile` on a wide plate, usually an <Led />. */
    tile?: Snippet;
    onclick?: (e: MouseEvent) => void;
    children: Snippet;
  }
  let { variant = 'key', wide = false, type = 'button', disabled = false, pressed, tile, onclick, children }: Props = $props();
  const cls = $derived(`k-${variant}${wide ? ' wide' : ''}`);
</script>

<button class={cls} {type} {disabled} aria-pressed={pressed} {onclick}>
  {#if wide && tile}<span class="k-tile">{@render tile()}</span>{/if}
  {#if wide}<span class="k-label">{@render children()}</span>{:else}{@render children()}{/if}
</button>
