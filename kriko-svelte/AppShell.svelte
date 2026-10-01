<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { NavGroup } from './lib/types';
  import NavRail from './NavRail.svelte';

  interface Props {
    nav: NavGroup[];
    current: string;
    wordmark: string;
    crumb: string;
    title: string;
    lead: string;
    children: Snippet;
  }
  let { nav, current, wordmark, crumb, title, lead, children }: Props = $props();
</script>

<svelte:head><title>{title} · Kriko</title></svelte:head>

<div class="k-app">
  <NavRail groups={nav} {current} {wordmark} />
  <main class="k-main">
    <div class="k-crumb">kriko / <b>{crumb}</b></div>
    <h1 class="k-title">{title}</h1>
    <p class="k-lead">{lead}</p>
    {@render children()}
  </main>
</div>
