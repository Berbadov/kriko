<script lang="ts">
  import AppShell from '../AppShell.svelte';
  import Key from '../Key.svelte';
  import Led from '../Led.svelte';
  import Tag from '../Tag.svelte';
  import Meter from '../Meter.svelte';
  import Switch from '../Switch.svelte';
  import AgentIcon from '../AgentIcon.svelte';
  import { nav } from '../lib/nav';
  import { glyphs } from '../lib/glyphs';
  import { agents } from '../lib/sample';
  import wordmark from '../assets/kriko-wordmark-white.svg';

  let product = $state('');
  let question = $state('');
  let packsFirst = $state(true);
  let askFirst = $state(true);
  let allowed = $state(Object.fromEntries(agents.map((a) => [a.id, a.allowed])));
  let progress = $state(76);
</script>

<AppShell {nav} current="run" {wordmark} crumb="run" title="Run" lead="Start a check and choose which agents are allowed to do the reading.">
  <div class="k-grid k-g2">
    <div class="k-card" style="display:grid;gap:24px">
      <div><div class="k-eyebrow" style="margin-bottom:10px">Product</div><label class="k-input"><input bind:value={product} placeholder="Name a product or paste a link" /></label></div>
      <div><div class="k-eyebrow" style="margin-bottom:10px">Question</div><label class="k-input"><input bind:value={question} placeholder="What should Kriko decide?" /></label></div>
      <div class="k-spread"><div><div style="font-weight:600">Use existing packs first</div><div class="k-note">Skip sources already in the store</div></div><Switch bind:checked={packsFirst} label="Use existing packs first" /></div>
      <div class="k-spread"><div><div style="font-weight:600">Ask before reading new sites</div><div class="k-note">Pauses the run for your approval</div></div><Switch bind:checked={askFirst} label="Ask before reading new sites" /></div>
      <div class="k-row">
        <Key variant="plate" wide disabled={!product.trim()}>
          {#snippet tile()}<span style="--dot:5px;--gap:2px;--led:var(--ice)"><Led rows={glyphs.scan5} /></span>{/snippet}
          Start run
        </Key>
        <Key variant="ghost">Save as draft</Key>
      </div>
    </div>
    <div class="k-card">
      <h2>Agents</h2>
      {#each agents.slice(0, 4) as a (a.id)}
        <div class="k-spread" style="padding:12px 0;box-shadow:inset 0 -1px 0 var(--hairline)">
          <div class="k-row" style="gap:14px;flex-wrap:nowrap"><AgentIcon name={a.name} src={a.icon} /><div><div style="font-weight:600">{a.name}</div><div class="k-note">{a.kind}</div></div></div>
          <Switch bind:checked={allowed[a.id]} label={a.name} />
        </div>
      {/each}
      <p class="k-note" style="margin-top:16px">Agents that are switched off are never started.</p>
    </div>
  </div>

  <div class="k-card" style="margin-top:24px">
    <div class="k-spread" style="margin-bottom:14px"><h2 style="margin:0">Run 14</h2><Tag state="live">Live</Tag></div>
    <div class="k-note" style="margin-bottom:8px">{progress}% · reading review pages</div>
    <Meter value={progress} live />
  </div>
</AppShell>
