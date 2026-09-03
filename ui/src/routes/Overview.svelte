<script lang="ts">
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { isLive } from "../lib/jobs";
    import { hashWith, route } from "../lib/router";

    // Five counts and a table that duplicated History did not answer "what
    // should I work on". Everything here is either work waiting or a link to
    // where that work is done.
    const load = async () => {
        const [status, packs, updates, jobs, weakest] = await Promise.all([
            api.status(),
            api.packs(),
            api.packUpdates().catch(() => null),
            api.jobs(10).catch(() => ({ items: [] })),
            api.weakest(5).catch(() => ({ claims: [] })),
        ]);
        const gapLists = await Promise.all(
            packs.map((pack) => api.gaps(pack.pack_id).catch(() => [])),
        );
        return {
            status,
            packs,
            gaps: gapLists.flat().length,
            updatable: (updates?.packs ?? []).filter((p) => p.state === "available")
                .length,
            live: (jobs.items ?? []).filter(isLive).length,
            weakest: weakest.claims,
        };
    };
    const data = load();

    const link = (name: string) => hashWith({ mode: $route.query.mode }, name);

    const plural = (n: number, one: string, many: string) =>
        `${n} ${n === 1 ? one : many}`;
</script>

<h2>Overview</h2>

<Async promise={data}>
    {#snippet children(d)}
        {#if !d.packs.length}
            <EmptyState
                title="No packs installed"
                detail="The engine holds no knowledge yet, so nothing here has anything to
                        report. Install a pack and this page fills in."
                actionLabel="Open Packs"
                actionHref={link("packs")}
            />
        {:else}
            <ul class="worklist">
                <li>
                    <a href={link("coverage")}
                        >{plural(d.gaps, "coverage gap", "coverage gaps")}</a
                    >
                    <span class="meta"
                        >subjects a pack names but knows nothing about</span
                    >
                </li>
                <li>
                    <a href={link("packs")}
                        >{plural(d.updatable, "pack update", "pack updates")} waiting</a
                    >
                    <span class="meta">knowledge moves weekly; the app rarely</span>
                </li>
                <li>
                    <a href={link("jobs")}
                        >{plural(d.live, "run in flight", "runs in flight")}</a
                    >
                    <span class="meta">research and pack builds outlive the page</span>
                </li>
            </ul>

            <div class="stats">
                {#each [["Packs", d.status.packs], ["Enabled", d.status.enabled_packs], ["Subjects", d.status.counts.subjects ?? 0], ["Claims", d.status.counts.claims ?? 0]] as [label, value] (label)}
                    <div class="stat"><strong>{value}</strong><span>{label}</span></div>
                {/each}
            </div>

            <h3>Thinnest evidence</h3>
            <p class="meta">
                The claims we ship with the least behind them. Fixing these is worth more
                than adding new ones.
            </p>
            {#if d.weakest.length}
                <ul class="worklist">
                    {#each d.weakest as claim (claim.claim_id)}
                        <li>
                            <a href={link("health")}>{claim.title}</a>
                            <span class="meta"
                                >{claim.subject_label} · {claim.independent_sources}
                                independent source(s) · best {claim.best_tier}</span
                            >
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="meta">
                    Nothing reported — every shipped claim has sources behind it.
                </p>
            {/if}
        {/if}
    {/snippet}
</Async>
