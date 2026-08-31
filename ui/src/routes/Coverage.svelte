<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";

    const load = async () => {
        const packs = await api.packs();
        return Promise.all(
            packs.map(async (pack) => ({ pack, gaps: await api.gaps(pack.pack_id) })),
        );
    };
    const data = load();
</script>

<h2>Coverage gaps</h2>
<Async promise={data}>
    {#snippet children(sections)}
        {#if !sections.length}
            <p class="state empty">No packs installed.</p>
        {/if}
        {#each sections as { pack, gaps } (pack.pack_id)}
            <article class="card">
                <h3>{pack.name} <span class="badge">{gaps.length} gap(s)</span></h3>
                {#if gaps.length}
                    <ul>
                        {#each gaps as gap}
                            <li>{gap.label} <span class="meta">({gap.kind})</span></li>
                        {/each}
                    </ul>
                {:else}
                    <p class="state empty">No coverage gaps reported.</p>
                {/if}
            </article>
        {/each}
    {/snippet}
</Async>
