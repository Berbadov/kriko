<script lang="ts">
    import { word } from "../lib/plural";
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { isLive } from "../lib/jobs";
    import { hashWith, route } from "../lib/router";
    import { SvelteSet } from "svelte/reactivity";

    // Five counts and a table that duplicated History did not answer "what
    // should I work on". Everything here is either work waiting or a link to
    // where that work is done.
    //
    // Pack updates is deliberately not in this Promise.all. It is the one
    // call here backed by a remote fetch rather than local data, and joining
    // it meant the whole screen — packs, jobs, coverage, everything local —
    // waited on whichever call was slowest, up to the server's own 15s
    // timeout when the index was unreachable (B145 desktop-2). It resolves
    // into its own state below and patches the worklist in once it lands.
    const load = async () => {
        const [status, packs, jobs, weakest, unmapped] = await Promise.all([
            api.status(),
            api.packs(),
            api.jobs(10).catch(() => ({ items: [] })),
            api.weakest(5).catch(() => ({ claims: [] })),
            api.unmappedLabels(8).catch(() => ({ labels: [] })),
        ]);
        const gapLists = await Promise.all(
            packs.map((pack) => api.gaps(pack.pack_id).catch(() => [])),
        );
        return {
            status,
            packs,
            gaps: gapLists.flat().length,
            live: (jobs.items ?? []).filter(isLive).length,
            weakest: weakest.claims,
            unmapped: unmapped.labels,
        };
    };
    const data = load();

    // "0 pack updates waiting" and "could not check" are different answers
    // (B145 knowledge-9): the first is a genuine all-clear, the second means
    // nothing was learned at all and showing a zero would say otherwise.
    // `updatable` stays null until the check lands, which reads as neither.
    let updatable = $state<number | null>(null);
    let updatesFailed = $state(false);
    api.packUpdates()
        .then((u) => {
            updatesFailed = Boolean(u.error);
            updatable = u.error ? null : u.packs.filter((p) => p.state === "available").length;
        })
        .catch(() => {
            updatesFailed = true;
        });

    const link = (name: string) => hashWith({ mode: $route.query.mode }, name);

    const plural = (n: number, one: string, many: string) =>
        `${n} ${n === 1 ? one : many}`;

    // Dismissed in place rather than by reloading the page: the row is struck
    // through and left visible, because a row that vanishes under the cursor
    // gives the reader no way to tell "dismissed" from "misclicked".
    let forgotten = $state(new SvelteSet<string>());

    async function forget(adapterId: string, label: string) {
        const key = adapterId + "/" + label;
        forgotten.add(key);
        try {
            await api.forgetLabel(adapterId, label);
        } catch {
            // Put it back: a label still on the server must still be on screen.
            forgotten.delete(key);
        }
    }
</script>

<h2>Overview</h2>

<Async promise={data}>
    <!-- Overview's shape is fixed — three work items, then four counts — so the
         skeleton is honest here in a way it would not be on a result page whose
         length depends on what came back. -->
    {#snippet skeleton()}
        <ul class="worklist">
            {#each [0, 1, 2] as row (row)}
                <li><span class="skeleton">a work item waiting to be counted</span></li>
            {/each}
        </ul>
        <div class="stats">
            {#each [0, 1, 2, 3] as cell (cell)}
                <div class="stat skeleton">0</div>
            {/each}
        </div>
    {/snippet}
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
                    {#if updatesFailed}
                        <a href={link("packs")}>Could not check for pack updates</a>
                        <span class="meta">installed packs keep working either way</span>
                    {:else if updatable === null}
                        <a href={link("packs")}>Checking for pack updates…</a>
                        <span class="meta">knowledge moves weekly; the app rarely</span>
                    {:else}
                        <a href={link("packs")}
                            >{plural(updatable, "pack update", "pack updates")} waiting</a
                        >
                        <span class="meta">knowledge moves weekly; the app rarely</span>
                    {/if}
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

            <h3>Labels no adapter reads</h3>
            <p class="meta">
                Fields the listing pages carried that no installed adapter maps.
                Not errors — this is the only warning a site gives when it
                renames a field, because nothing fails when it does: the lookup
                still succeeds, resolves less precisely and returns fewer
                claims, which reads as a thin pack rather than a broken
                adapter.
            </p>
            {#if d.unmapped.length}
                <table>
                    <thead>
                        <tr>
                            <th>Label</th>
                            <th>Site</th>
                            <th class="num">Seen</th>
                            <th>Last</th>
                            <th><span class="sr-only">Dismiss</span></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each d.unmapped as row (row.adapter_id + "/" + row.label)}
                            <tr class:gone={forgotten.has(row.adapter_id + "/" + row.label)}>
                                <td>
                                    {#if row.sample_url}
                                        <a href={row.sample_url} target="_blank" rel="noreferrer"
                                            >{row.label}</a
                                        >
                                    {:else}
                                        {row.label}
                                    {/if}
                                </td>
                                <td class="meta">{row.adapter_id}</td>
                                <td class="num">{row.seen}</td>
                                <td class="meta">{row.last_at.slice(0, 10)}</td>
                                <td>
                                    <!-- A list that cannot be pruned stops
                                         being read, and some labels are never
                                         going to be mapped. Dismissal is a
                                         delete, so a label that recurs comes
                                         back — which is the honest answer to
                                         "I dismissed this and it is still
                                         happening". -->
                                    <button
                                        class="link-ish"
                                        onclick={() => forget(row.adapter_id, row.label)}
                                        disabled={forgotten.has(row.adapter_id + "/" + row.label)}
                                        >Not a field</button
                                    >
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {:else}
                <p class="meta">
                    Nothing unread — every label the pages carried has a rule
                    behind it. This fills in as listings are checked.
                </p>
            {/if}

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
                                independent {word(claim.independent_sources, "source")} · best {claim.best_tier}</span
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
