<script lang="ts">
  import type { VerdictKind } from './lib/types';
  import { glyphs } from './lib/glyphs';
  import Led from './Led.svelte';

  let { kind }: { kind: VerdictKind } = $props();
  const text = { rec: 'Recommended', weigh: 'Weigh up', avoid: 'Avoid' } as const;
  const glyph = { rec: 'check5', weigh: 'queue5', avoid: 'x5' } as const;
</script>

<span class="k-verdict" data-v={kind}><Led rows={glyphs[glyph[kind]]} />{text[kind]}</span>
