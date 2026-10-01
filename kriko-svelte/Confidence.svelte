<script lang="ts">
  import Meter from './Meter.svelte';
  let { value }: { value: number } = $props();
</script>

<span class="k-conf"><Meter {value} segments={10} slim />{value}%</span>
