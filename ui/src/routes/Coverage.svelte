<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";
    import { follow, stateWord } from "../lib/jobs";
    import type { Gap, Job } from "../lib/types";

    const load = async () => {
        const packs = await api.packs();
        return Promise.all(
            packs.map(async (pack) => ({ pack, gaps: await api.gaps(pack.pack_id) })),
        );
    };
    const data = load();

    // A gap is only interesting if you can act on it, and until now acting on
    // it meant leaving the browser for a terminal. Keyed by subject so the
    // status lands on the row that started it.
    let started = $state<Record<string, Job>>({});

    async function research(gap: Gap, packId: string) {
        try {
            const { job_id } = await api.research({
                subject_id: gap.subject_id,
                pack_id: packId,
            });
            const job = await api.job(job_id);
            started = { ...started, [gap.subject_id]: job };
            follow(job_id, (update) => {
                started = { ...started, [gap.subject_id]: update };
            });
        } catch (cause) {
            // Reported inline rather than thrown: one gap failing to start
            // must not take the whole coverage report down with it.
            started = {
                ...started,
                [gap.subject_id]: {
                    state: "failed",
                    message: String(cause),
                    done: true,
                } as Job,
            };
        }
    }
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
                        {#each gaps as gap (gap.subject_id)}
                            <li class="gap">
                                <span>{gap.label} <span class="meta">({gap.kind})</span></span>
                                {#if started[gap.subject_id]}
                                    <span class="badge state-{started[gap.subject_id].state}"
                                        >{stateWord(started[gap.subject_id])}</span
                                    >
                                    <span class="meta">{started[gap.subject_id].message}</span>
                                {:else}
                                    <button onclick={() => research(gap, pack.pack_id)}
                                        >Research</button
                                    >
                                {/if}
                            </li>
                        {/each}
                    </ul>
                {:else}
                    <p class="state empty">No coverage gaps reported.</p>
                {/if}
            </article>
        {/each}
    {/snippet}
</Async>
