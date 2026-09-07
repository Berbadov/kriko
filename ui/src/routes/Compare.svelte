<script lang="ts">
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { compareMany } from "../lib/compare";
    import { severityWord } from "../lib/report";
    import { hashWith, route, setQuery } from "../lib/router";
    import type { HistoryItem } from "../lib/types";

    //: Four is the cap, and it is a layout limit rather than a logical one:
    //: `compareMany` takes any number, but a fifth column stops fitting the
    //: measure and a shortlist longer than four is not a shortlist.
    const MAX = 4;

    let items = $state<HistoryItem[]>([]);

    // The ids live in the URL so a comparison stays a link someone can paste,
    // the same reason mode does. `left`/`right` are still read because every
    // Report page links here with `?left=`, and a link that stops working is
    // a worse cost than carrying two spellings.
    const ids = $derived(
        ($route.query.ids
            ? $route.query.ids.split(",")
            : [$route.query.left ?? "", $route.query.right ?? ""]
        )
            .map((id) => id.trim())
            .filter(Boolean)
            .filter((id, i, all) => all.indexOf(id) === i)
            .slice(0, MAX),
    );

    // Always at least two, and one trailing empty slot beyond what is chosen:
    // two because a comparison screen showing one picker does not read as a
    // comparison, and the trailing one so adding a third is a visible act
    // rather than a feature the reader has to be told about.
    const slots = $derived(
        ids.length < MAX ? [...ids, ...Array(Math.max(1, 2 - ids.length)).fill("")] : ids,
    );

    function choose(index: number, value: string) {
        const next = [...ids];
        if (value) next[index] = value;
        else next.splice(index, 1);
        setQuery("ids", next.filter(Boolean).join(",") || undefined);
    }

    const listed = api.history(50).then((h) => (items = h.items));

    const lined = $derived(
        ids.length >= 2
            ? Promise.all(ids.map((id) => api.getLookup(id))).then((answers) => ({
                  answers,
                  diff: compareMany(answers),
              }))
            : null,
    );
</script>

<h2>Compare saved checks</h2>

<Async promise={listed} loading="Loading history…">
    {#snippet children()}
        {#if items.length < 2}
            <EmptyState
                title="Compare needs two saved checks"
                detail="Run a check on each of the ones you are weighing up and they will
                        all be here — up to four at a time."
                actionLabel="Run a check"
                actionHref={hashWith({ mode: $route.query.mode }, "check")}
            />
        {:else}
            <div class="row slots">
                {#each slots as id, index (index)}
                    <div class="field">
                        <label for="slot-{index}">
                            {index === 0 ? "First" : index === 1 ? "Second" : `#${index + 1}`}
                        </label>
                        <select
                            id="slot-{index}"
                            value={id}
                            onchange={(e) => choose(index, e.currentTarget.value)}
                        >
                            <option value="">{index < 2 ? "choose…" : "add another…"}</option>
                            {#each items as item (item.lookup_id)}
                                <option
                                    value={item.lookup_id}
                                    disabled={item.lookup_id !== id &&
                                        ids.includes(item.lookup_id)}>{item.label}</option
                                >
                            {/each}
                        </select>
                    </div>
                {/each}
            </div>

            {#if lined}
                <Async promise={lined} loading="Loading the answers…">
                    {#snippet children(d)}
                        <p class="lede-compare">
                            {d.diff.shared}{d.answers.length === 2
                                ? " in both"
                                : ` in all ${d.answers.length}`} · {d.diff.only
                                .map(
                                    (n: number, i: number) =>
                                        `${n} only in ${d.answers[i].label}`,
                                )
                                .join(" · ")}
                        </p>
                        <div class="table-scroll">
                            <table class="compare">
                                <thead>
                                    <tr>
                                        <th scope="col">Known risk</th>
                                        {#each d.answers as answer (answer.lookup_id)}
                                            <th scope="col">{answer.label}</th>
                                        {/each}
                                    </tr>
                                </thead>
                                <tbody>
                                    {#each d.diff.rows as row (row.key)}
                                        <tr>
                                            <th scope="row">{row.title}</th>
                                            {#each row.cells as cell, i (i)}
                                                <td>
                                                    {#if cell}
                                                        <span class="sev {cell.severity}"
                                                            >{severityWord(cell.severity)}</span
                                                        >
                                                    {:else}<span class="meta">—</span>{/if}
                                                </td>
                                            {/each}
                                        </tr>
                                    {/each}
                                </tbody>
                            </table>
                        </div>
                        <p class="meta">
                            A dash means no installed pack holds that risk for that one —
                            not that it has been ruled out.
                        </p>
                    {/snippet}
                </Async>
            {:else}
                <p class="meta">Pick at least two different saved checks to line them up.</p>
            {/if}
        {/if}
    {/snippet}
</Async>
