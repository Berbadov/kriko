<script lang="ts">
  import AppShell from '../AppShell.svelte';
  import Key from '../Key.svelte';
  import Tag from '../Tag.svelte';
  import { nav } from '../lib/nav';
  import { knowledge } from '../lib/sample';
  import wordmark from '../assets/kriko-wordmark-white.svg';

  let filter = $state('');
  const rows = $derived(
    knowledge.filter((r) => `${r.subject} ${r.attribute} ${r.value}`.toLowerCase().includes(filter.trim().toLowerCase())),
  );
</script>

<AppShell {nav} current="browse" {wordmark} crumb="knowledge / browse" title="Browse" lead="Search every subject, attribute and claim stored on this machine.">
  <div style="max-width:520px;margin-bottom:24px"><label class="k-input"><input bind:value={filter} placeholder="Filter subjects, attributes and values" /></label></div>
  <div class="k-card">
    <table class="k-table">
      <thead><tr><th>Subject</th><th>Attribute</th><th>Value</th><th class="r">Claims</th><th class="r">Sources</th><th>Trust</th></tr></thead>
      <tbody>
        {#each rows as r (r.subject + r.attribute)}
          <tr>
            <td style="font-weight:600">{r.subject}</td><td>{r.attribute}</td><td class="m">{r.value}</td>
            <td class="m r">{r.claims}</td><td class="m r">{r.sources}</td>
            <td><Tag state={r.trust}>{r.trustLabel}</Tag></td>
          </tr>
        {:else}
          <tr><td colspan="6" class="m">Nothing matches. Clear the filter to see all 760.</td></tr>
        {/each}
      </tbody>
    </table>
    <div class="k-spread" style="margin-top:20px"><span class="k-note">{rows.length} of 760</span><div class="k-row"><Key variant="plate">Previous</Key><Key variant="plate">Next</Key></div></div>
  </div>
</AppShell>
