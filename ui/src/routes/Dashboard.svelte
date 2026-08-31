<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";

    const load = async () => {
        const [status, activity] = await Promise.all([api.status(), api.activity()]);
        return { status, activity };
    };
    const data = load();
</script>

<h2>Dashboard</h2>
<Async promise={data}>
    {#snippet children({ status, activity })}
        <div class="stats">
            {#each [["Packs", status.packs], ["Enabled", status.enabled_packs], ["Subjects", status.counts.subjects], ["Claims", status.counts.claims], ["Analyses", activity.items.length]] as [label, value]}
                <div class="stat"><strong>{value}</strong><span>{label}</span></div>
            {/each}
        </div>

        <h2>Recent analysis activity</h2>
        {#if activity.items.length}
            <table>
                <thead>
                    <tr
                        ><th>When</th><th>URL</th><th>Method</th><th>Coverage</th><th
                            >Claims</th
                        ></tr
                    >
                </thead>
                <tbody>
                    {#each activity.items as item}
                        <tr>
                            <td class="meta">{item.timestamp ?? item.created_at ?? "—"}</td>
                            <td>{item.url ?? "—"}</td>
                            <td>{item.method ?? "—"}</td>
                            <td>{item.coverage ?? "—"}</td>
                            <td class="num">{item.claim_titles?.length ?? "—"}</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {:else}
            <p class="state empty">No analysis activity yet.</p>
        {/if}
    {/snippet}
</Async>
