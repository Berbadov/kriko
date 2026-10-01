<script lang="ts">
  import AppShell from '../AppShell.svelte';
  import Key from '../Key.svelte';
  import Tag from '../Tag.svelte';
  import Verdict from '../Verdict.svelte';
  import Confidence from '../Confidence.svelte';
  import Segmented from '../Segmented.svelte';
  import { nav } from '../lib/nav';
  import { products } from '../lib/sample';
  import wordmark from '../assets/kriko-wordmark-white.svg';

  type Layout = 'columns' | 'rows';
  let layout = $state<Layout>('columns');
  const options = [
    { value: 'columns', label: 'Columns', glyph: 'cols' },
    { value: 'rows', label: 'Rows', glyph: 'list' },
  ] as const;
</script>

<AppShell {nav} current="compare" {wordmark} crumb="compare" title="Compare" lead="Weigh products side by side, with the evidence behind every cell.">
  <div class="k-spread" style="margin-bottom:24px">
    <div class="k-row"><Key variant="plate">Add product</Key><Key variant="plate">Share</Key></div>
    <Segmented options={[...options]} bind:value={layout} label="Layout" />
  </div>

  <div class="k-grid" class:k-g3={layout === 'columns'}>
    {#each products as p (p.name)}
      <div class="k-card">
        <div class="k-eyebrow">Product</div>
        <div style="font:600 28px/32px var(--font-display);letter-spacing:.03em;text-transform:uppercase;margin:6px 0 14px">{p.name}</div>
        <div style="margin-bottom:8px"><Verdict kind={p.verdict} /></div>
        <Confidence value={p.confidence} />
        <div style="margin-top:18px">
          {#each p.attributes as a (a.label)}
            <div style="padding:14px 0;box-shadow:inset 0 -1px 0 var(--hairline)">
              <div class="k-note">{a.label}</div>
              <div style="margin-top:4px;font-weight:600" style:color={a.best ? 'var(--ice)' : undefined}>{a.value}</div>
              <div class="k-note" style="margin-top:6px">{a.sources} sources</div>
            </div>
          {/each}
        </div>
      </div>
    {/each}
  </div>

  <div class="k-callout" style="margin-top:24px">
    <div><Tag state="need">Needs you</Tag><div style="margin-top:10px;font-weight:600">One disagreement stops a verdict on Product B.</div></div>
    <Key>Settle claim</Key>
  </div>
</AppShell>
