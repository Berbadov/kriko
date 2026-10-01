<script lang="ts">
  import type { NavGroup } from './lib/types';

  interface Props {
    groups: NavGroup[];
    /** key of the current item */
    current: string;
    /** the white wordmark file, assets/Logos/kriko-wordmark-white.svg */
    wordmark: string;
    tagline?: string;
  }
  let { groups, current, wordmark, tagline = 'local product knowledge' }: Props = $props();
</script>

<aside class="k-side">
  <a class="k-brandblock" href="/home"><img src={wordmark} alt="Kriko" /><span>{tagline}</span></a>
  <nav class="k-nav" aria-label="Main">
    {#each groups as g (g.label)}
      <div class="k-navlabel">{g.label}</div>
      {#each g.items as it (it.key)}
        <a class="k-navitem" href={it.href} aria-current={it.key === current ? 'page' : undefined}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d={it.icon} /></svg>
          {it.label}
          {#if it.count !== undefined}<span class="n">{it.count}</span>{/if}
        </a>
      {/each}
    {/each}
  </nav>
</aside>
