<script lang="ts">
  import { letters } from './lib/glyphs';
  import Led from './Led.svelte';

  interface Props {
    name: string;
    /** Official vendor icon file from assets/Agents. Never draw or recolour a vendor mark. */
    src?: string;
  }
  let { name, src }: Props = $props();
  const rows = $derived(letters[name.charAt(0).toUpperCase()] ?? letters.K);
</script>

<span class="k-agent">
  {#if src}<img {src} alt="" width="24" height="24" />{:else}<Led rows={rows} />{/if}
</span>
