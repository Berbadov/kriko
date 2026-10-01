<script lang="ts">
  import AppShell from '../AppShell.svelte';
  import Key from '../Key.svelte';
  import Tag from '../Tag.svelte';
  import Switch from '../Switch.svelte';
  import AgentIcon from '../AgentIcon.svelte';
  import { nav } from '../lib/nav';
  import { agents as source } from '../lib/sample';
  import wordmark from '../assets/kriko-wordmark-white.svg';

  let agents = $state(source.map((a) => ({ ...a })));
  const connected = $derived(agents.filter((a) => a.state === 'live').length);
</script>

<AppShell {nav} current="agents" {wordmark} crumb="system / agents" title="Agents" lead="See which command-line agents Kriko found and which ones may read for you.">
  <div class="k-spread" style="margin-bottom:24px">
    <span class="k-note">{agents.length} found · {connected} connected · all data remains on this machine</span>
    <div class="k-row"><Key variant="plate">Rescan</Key><Key>Add agent</Key></div>
  </div>
  <div class="k-card">
    <table class="k-table">
      <thead><tr><th>Agent</th><th>State</th><th class="r">Latency</th><th class="r">Allowed</th></tr></thead>
      <tbody>
        {#each agents as a (a.id)}
          <tr>
            <td><div class="k-row" style="gap:14px;flex-wrap:nowrap"><AgentIcon name={a.name} src={a.icon} /><div><div style="font-weight:600">{a.name}</div><div class="k-note">{a.kind}</div></div></div></td>
            <td><Tag state={a.state}>{a.stateLabel}</Tag></td>
            <td class="m r">{a.latency}</td>
            <td class="r"><Switch bind:checked={a.allowed} label={`Allow ${a.name}`} /></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</AppShell>
