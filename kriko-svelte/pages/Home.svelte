<script lang="ts">
  import AppShell from '../AppShell.svelte';
  import Key from '../Key.svelte';
  import Tag from '../Tag.svelte';
  import Verdict from '../Verdict.svelte';
  import Confidence from '../Confidence.svelte';
  import { nav } from '../lib/nav';
  import type { VerdictKind } from '../lib/types';
  import wordmark from '../assets/kriko-wordmark-white.svg';

  let query = $state('');
  const totals = [
    { label: 'Subjects', value: 93, note: 'in 7 packs' },
    { label: 'Claims', value: 754, note: '724 with evidence' },
    { label: 'Sources', value: 198, note: 'read locally' },
  ];
  const recent: { name: string; pack: string; verdict: VerdictKind; confidence: number; when: string }[] = [
    { name: 'Product A earbuds', pack: 'samsung.headphones', verdict: 'rec', confidence: 82, when: '2 min ago' },
    { name: 'Product B earbuds', pack: 'samsung.headphones', verdict: 'weigh', confidence: 61, when: 'Yesterday' },
  ];
</script>

<AppShell {nav} current="home" {wordmark} crumb="home" title="Home" lead="Check a product, resume a run, or see what Kriko already knows.">
  <form class="k-card" style="margin-bottom:24px" onsubmit={(e) => { e.preventDefault(); /* start check(query) */ }}>
    <div class="k-eyebrow" style="margin-bottom:12px">Check a product</div>
    <div class="k-row" style="flex-wrap:nowrap">
      <label class="k-input" style="flex:1"><input placeholder="Name a product or paste a link" bind:value={query} /></label>
      <Key type="submit" disabled={!query.trim()}>Start check</Key>
    </div>
    <p class="k-note" style="margin-top:12px">Everything runs on this machine. No data leaves the CLIs for their LLMs.</p>
  </form>

  <div class="k-grid k-g3" style="margin-bottom:24px">
    {#each totals as t (t.label)}
      <div class="k-card">
        <div class="k-eyebrow">{t.label}</div>
        <div class="k-row" style="margin-top:12px;align-items:baseline"><span class="k-num">{t.value}</span><span class="k-note">{t.note}</span></div>
      </div>
    {/each}
  </div>

  <div class="k-callout" style="margin-bottom:24px">
    <div>
      <Tag state="need">Needs you</Tag>
      <div style="margin-top:10px;font-weight:600">Run 14 is waiting on your decision about Product B.</div>
      <div class="k-note" style="margin-top:4px">Two sources disagree on battery life</div>
    </div>
    <Key variant="plate">Open run</Key>
  </div>

  <div class="k-card">
    <h2>Recent checks</h2>
    <table class="k-table">
      <thead><tr><th>Product</th><th>Verdict</th><th>Confidence</th><th class="r">When</th></tr></thead>
      <tbody>
        {#each recent as r (r.name)}
          <tr>
            <td><div style="font-weight:600">{r.name}</div><div class="k-note">pack · {r.pack}</div></td>
            <td><Verdict kind={r.verdict} /></td>
            <td><Confidence value={r.confidence} /></td>
            <td class="m r">{r.when}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</AppShell>
