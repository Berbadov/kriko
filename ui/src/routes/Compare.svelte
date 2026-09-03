<script lang="ts">
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { compare } from "../lib/compare";
    import { severityWord } from "../lib/report";
    import { hashWith, route, setQuery } from "../lib/router";
    import type { HistoryItem } from "../lib/types";

    let items = $state<HistoryItem[]>([]);

    const left = $derived($route.query.left ?? "");
    const right = $derived($route.query.right ?? "");
    const chosen = $derived(Boolean(left && right && left !== right));

    const listed = api.history(50).then((h) => (items = h.items));

    // The two ids live in the URL, so a comparison is a link someone can
    // paste — the same reason mode does.
    const pair = $derived(
        chosen
            ? Promise.all([api.getLookup(left), api.getLookup(right)]).then(([a, b]) => ({
                  a,
                  b,
                  diff: compare(a, b),
              }))
            : null,
    );
</script>

<h2>Compare two checks</h2>

<Async promise={listed} loading="Loading history…">
    {#snippet children()}
        {#if items.length < 2}
            <EmptyState
                title="Compare needs two saved checks"
                detail="Run a check on each of the two you are weighing up and they will
                        both be here."
                actionLabel="Run a check"
                actionHref={hashWith({ mode: $route.query.mode }, "check")}
            />
        {:else}
            <div class="row">
                <div class="field">
                    <label for="left">First</label>
                    <select
                        id="left"
                        value={left}
                        onchange={(e) => setQuery("left", e.currentTarget.value)}
                    >
                        <option value="">choose…</option>
                        {#each items as item (item.lookup_id)}
                            <option value={item.lookup_id}>{item.label}</option>
                        {/each}
                    </select>
                </div>
                <div class="field">
                    <label for="right">Second</label>
                    <select
                        id="right"
                        value={right}
                        onchange={(e) => setQuery("right", e.currentTarget.value)}
                    >
                        <option value="">choose…</option>
                        {#each items as item (item.lookup_id)}
                            <option value={item.lookup_id}>{item.label}</option>
                        {/each}
                    </select>
                </div>
            </div>

            {#if pair}
                <Async promise={pair} loading="Loading both answers…">
                    {#snippet children(d)}
                        <p class="lede-compare">
                            {d.diff.shared} in both · {d.diff.onlyLeft} only in
                            {d.a.label} · {d.diff.onlyRight} only in {d.b.label}
                        </p>
                        <table class="compare">
                            <thead>
                                <tr>
                                    <th scope="col">Known risk</th>
                                    <th scope="col">{d.a.label}</th>
                                    <th scope="col">{d.b.label}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {#each d.diff.rows as row (row.key)}
                                    <tr>
                                        <th scope="row">{row.title}</th>
                                        <td>
                                            {#if row.left}
                                                <span class="sev {row.left.severity}"
                                                    >{severityWord(row.left.severity)}</span
                                                >
                                            {:else}<span class="meta">—</span>{/if}
                                        </td>
                                        <td>
                                            {#if row.right}
                                                <span class="sev {row.right.severity}"
                                                    >{severityWord(row.right.severity)}</span
                                                >
                                            {:else}<span class="meta">—</span>{/if}
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    {/snippet}
                </Async>
            {:else}
                <p class="meta">Pick two different saved checks to line them up.</p>
            {/if}
        {/if}
    {/snippet}
</Async>
