<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { TagState } from './lib/types';
  import { glyphs } from './lib/glyphs';
  import Led from './Led.svelte';

  interface Props {
    state: TagState;
    children: Snippet;
  }
  let { state, children }: Props = $props();
  // State is always a word plus a glyph, never colour alone.
  const glyph = { live: 'bang5', need: 'bang5', queue: 'queue5', done: 'check5', block: 'x5' } as const;
</script>

<span class="k-tag" data-state={state}>
  <Led rows={glyphs[glyph[state]]} anim={state === 'need' ? 'blink' : state === 'live' ? 'boot' : undefined} />
  {@render children()}
</span>
