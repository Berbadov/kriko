<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import { word } from "../lib/plural";
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { isLive } from "../lib/jobs";
    import { hashWith, toHash } from "../lib/router";
    import { SvelteSet } from "svelte/reactivity";
import PageHead from "../lib/kriko/PageHead.svelte";

    // Everything here is either work waiting or a link to where that work is
    // done (B179): each number and each row opens the screen, and the filter,
    // that holds what it counted. A figure that opens nothing is a report, and
    // the reader asked for a screen that "connects to nothing" to stop.
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
            api.unmappedLabels(100).catch(() => ({ labels: [] })),
        ]);
        const gapLists = await Promise.all(
            packs.map((pack) => api.gaps(pack.pack_id).catch(() => [])),
        );
        return {
            status,
            packs,
            gaps: gapLists.flat().length,
            off: packs.filter((pack) => !pack.enabled).length,
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

    const link = (name: string) => toHash(name);
    // The installed catalogs are the folded line at the top of Browse.
    const catalogs = hashWith({ catalogs: "1" }, "knowledge");
    const gapsLens = hashWith({ lens: "gaps" }, "knowledge");

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

    // The labels table shows the first few and says how many there are; the
    // rest live on Sites, which the count links to.
    const SHOWN = 8;
</script>

<PageHead crumb="knowledge / overview" title="Overview" lead="What needs you now, and where the knowledge is thin." />

<Async promise={data}>
    <!-- Overview's shape is fixed — a worklist, then four counts — so the
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
                actionLabel="Open Catalogs"
                actionHref={link("knowledge")}
            />
        {:else}
            {@const off = d.off}
            <h3><Icon name="warn" /> Needs attention</h3>
            {@const any =
                d.gaps > 0 || off > 0 || d.unmapped.length > 0 || d.live > 0 ||
                updatesFailed || (updatable ?? 0) > 0}
            {#if any}
                <ul class="worklist">
                    {#if d.gaps}
                        <li>
                            <a href={gapsLens}
                                >{plural(d.gaps, "product with nothing known", "products with nothing known")}</a
                            >
                        </li>
                    {/if}
                    {#if updatesFailed}
                        <li><a href={catalogs}>Update check failed</a></li>
                    {:else if updatable}
                        <li>
                            <a href={catalogs}
                                >{plural(updatable, "catalog update", "catalog updates")} waiting</a
                            >
                        </li>
                    {/if}
                    {#if off}
                        <li>
                            <a href={catalogs}
                                >{plural(off, "catalog", "catalogs")} switched off</a
                            >
                        </li>
                    {/if}
                    {#if d.unmapped.length}
                        <li>
                            <a href={link("sites")}
                                >{plural(d.unmapped.length, "site label", "site labels")} no adapter reads</a
                            >
                        </li>
                    {/if}
                    {#if d.live}
                        <li>
                            <a href={link("jobs")}
                                >{plural(d.live, "run in flight", "runs in flight")}</a
                            >
                        </li>
                    {/if}
                </ul>
            {:else}
                <p class="meta">
                    {updatable === null && !updatesFailed
                        ? "Nothing so far. Checking for catalog updates."
                        : "Nothing needs attention."}
                </p>
            {/if}

            <div class="stats">
                <a class="stat" href={catalogs}
                    ><strong>{d.status.packs}</strong><span>Catalogs</span></a
                >
                <a class="stat" href={catalogs}
                    ><strong>{d.status.enabled_packs}</strong><span>On</span></a
                >
                <a class="stat" href={link("knowledge")}
                    ><strong>{(d.status.counts_enabled ?? d.status.counts).subjects ?? 0}</strong><span
                        >Subjects</span
                    ></a
                >
                <a class="stat" href={link("knowledge")}
                    ><strong>{(d.status.counts_enabled ?? d.status.counts).claims ?? 0}</strong><span
                        >Claims</span
                    ></a
                >
            </div>

            <h3><Icon name="tag" /> Labels no adapter reads</h3>
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
                        {#each d.unmapped.slice(0, SHOWN) as row (row.adapter_id + "/" + row.label)}
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
                                <td><a class="meta" href={link("sites")}>{row.adapter_id}</a></td>
                                <td class="num"><a href={link("sites")}>{row.seen}</a></td>
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
                {#if d.unmapped.length > SHOWN}
                    <p class="meta">
                        <a href={link("sites")}>All {d.unmapped.length} on Sites</a>
                    </p>
                {/if}
            {:else}
                <p class="meta">Nothing unread.</p>
            {/if}

            <h3><Icon name="chart" /> Thinnest evidence</h3>
            {#if d.weakest.length}
                <ul class="worklist">
                    {#each d.weakest as claim (claim.claim_id)}
                        <li>
                            <a href={hashWith({ lens: "weak" }, "knowledge", claim.claim_id)}
                                >{claim.title}</a
                            >
                            <span class="meta"
                                >{claim.subject_label} · {claim.independent_sources}
                                independent {word(claim.independent_sources, "source")} · best {claim.best_tier}</span
                            >
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="meta">Nothing reported.</p>
            {/if}
        {/if}
    {/snippet}
</Async>

<style>
    /* A count that opens something keeps the tile's look and gains the
       affordances of a link: no underline, a border that answers the pointer. */
    a.stat {
        color: inherit;
        text-decoration: none;
    }
    a.stat:hover {
        border-color: var(--accent);
    }
</style>
