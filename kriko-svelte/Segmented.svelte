<script lang="ts" generics="T extends string">
  import type { SegmentOption } from './lib/types';
  import { glyphs } from './lib/glyphs';
  import Led from './Led.svelte';

  interface Props {
    options: SegmentOption<T>[];
    value: T;
    label: string;
  }
  let { options, value = $bindable(), label }: Props = $props();
  const index = $derived(Math.max(0, options.findIndex((o) => o.value === value)));

  function onkeydown(e: KeyboardEvent) {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    value = options[(index + step + options.length) % options.length].value;
  }
</script>

<div class="k-seg" role="radiogroup" aria-label={label} style:--i={index}>
  <span class="thumb" style:--i={index}></span>
  {#each options as o (o.value)}
    <button role="radio" aria-checked={o.value === value} aria-label={o.label} tabindex={o.value === value ? 0 : -1} onclick={() => (value = o.value)} {onkeydown}>
      <Led rows={glyphs[o.glyph]} />
    </button>
  {/each}
</div>
