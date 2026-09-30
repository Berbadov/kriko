<script lang="ts">
    import Icon from "./Icon.svelte";
    import EmptyState from "./EmptyState.svelte";
    import { ApiError, api } from "./api";
    import { count } from "./plural";
    import { localTime, sourceWord } from "./report";
    import { navigate, route, toHash } from "./router";
    import { foldRepeats, groupByCategory, type HistoryEntry } from "./historyGroups";
    import type { HistoryItem } from "./types";

    let { page = false }: { page?: boolean } = $props();

    // The rail stays short on purpose (check-17): a Recent list a column
    // taller than the window is not "recent" any more. The page view starts
    // at the same size and grows with "Show older" instead of taking
    // everything the API will give it.
    const PAGE_SIZE = page ? 20 : 7;

    let items = $state<HistoryItem[]>([]);
    let limit = $state(PAGE_SIZE);
    let hasMore = $state(false);
    let notice = $state("");

    const link = (name: string, ...params: string[]) => toHash(name, ...params);

    async function refresh() {
        // One extra row is the whole trick: fetch limit+1 and if it comes
        // back, there is at least one more page to reach for.
        const got = (await api.history(limit + 1)).items;
        hasMore = got.length > limit;
        items = got.slice(0, limit);
    }

    function showOlder() {
        limit += PAGE_SIZE;
        refresh();
    }

    // Repeat checks of one product are one entry (B182), and forgetting the
    // entry forgets each check behind it: leaving the older ones would
    // bring the row back as if nothing had happened.
    async function forget(entry: HistoryEntry) {
        notice = "";
        for (const item of entry.checks) {
            try {
                await api.forget(item.lookup_id);
            } catch (e) {
                // Already gone is not a failure the reader caused (check-16): a
                // second window, or the extension, may have forgotten it first.
                // Any other error stays on screen rather than silently keeping a
                // dead row in the list.
                if (!(e instanceof ApiError && e.status === 404)) {
                    notice = "Could not forget that check. Try again.";
                    await refresh();
                    return;
                }
            }
        }
        // The open Result for any of these checks is a stale page the moment
        // its row is gone (check-32): its Handled boxes and notes would still
        // post, against a lookup the server no longer has.
        if (
            $route.name === "result" &&
            entry.checks.some((item) => item.lookup_id === $route.params[0])
        ) {
            navigate("history");
            return;
        }
        await refresh();
    }

    const ready = refresh();

    const entries = $derived(foldRepeats(items));
    const groups = $derived(groupByCategory(items));
    const forgetTitle = (entry: HistoryEntry) =>
        entry.checks.length > 1
            ? `Forget all ${entry.checks.length} checks of this`
            : "Forget this check";
</script>

{#snippet meta(entry: HistoryEntry)}
    {count(entry.latest.claim_count, "known risk")} · {sourceWord(entry.latest.source)}{#if page}
        {" · "}{localTime(entry.latest.created_at)}{/if}
{/snippet}

<svelte:element
    this={page ? "section" : "aside"}
    class={page ? "history page" : "history"}
>
    {#if !page}<h3><Icon name="history" /> Recent</h3>{/if}
    {#if notice}<p class="state">{notice}</p>{/if}
    {#await ready then}
        {#if items.length}
            {#if page}
                <p class="meta">
                    <a href={link("compare")}>Compare two of these →</a>
                </p>
                {#each groups as group (group.category)}
                    <section class="hgroup" aria-label={group.category || "No catalog"}>
                        <h3 class="hgroup-title">
                            <Icon name="layers" />
                            <span>{group.category || "No catalog"}</span>
                            <span class="hgroup-count"
                                >{count(group.total, "check")}</span
                            >
                        </h3>
                        <div class="hgrid">
                            {#each group.entries as entry (entry.latest.lookup_id)}
                                <article class="hcard">
                                    <a
                                        class="hcard-title"
                                        href={link("result", entry.latest.lookup_id)}
                                        >{entry.latest.label}</a
                                    >
                                    <span class="hcard-meta">
                                        <span
                                            class="badge"
                                            class:warn={entry.latest.claim_count > 0}
                                            >{count(entry.latest.claim_count, "known risk")}</span
                                        >
                                        {#if entry.checks.length > 1}
                                            <span class="badge" title="Checked {entry.checks.length} times"
                                                >{entry.checks.length} checks</span
                                            >
                                        {/if}
                                    </span>
                                    <span class="meta hcard-when"
                                        >{sourceWord(entry.latest.source)} · {localTime(
                                            entry.latest.created_at,
                                        )}</span
                                    >
                                    <button
                                        class="ghost small history-forget"
                                        title={forgetTitle(entry)}
                                        onclick={() => forget(entry)}>Forget</button
                                    >
                                </article>
                            {/each}
                        </div>
                    </section>
                {/each}
            {:else}
                <ul>
                    {#each entries as entry (entry.latest.lookup_id)}
                        <li>
                            <a
                                class="history-title"
                                href={link("result", entry.latest.lookup_id)}
                                >{entry.latest.label}</a
                            >
                            <span class="meta"
                                >{@render meta(entry)}{#if entry.checks.length > 1}
                                    {" · "}{entry.checks.length} checks{/if}</span
                            >
                            <!-- `small`, and titled rather than captioned in the rail: one
                                 full-size button per row turned a seven-item list into a
                                 column of seven buttons taller than the screen it sat
                                 beside. -->
                            <button
                                class="ghost small history-forget"
                                title={forgetTitle(entry)}
                                onclick={() => forget(entry)}>Forget</button
                            >
                        </li>
                    {/each}
                </ul>
            {/if}
            {#if page && hasMore}
                <button class="ghost" onclick={showOlder}>Show older</button>
            {/if}
        {:else}
            <EmptyState
                title="Nothing asked yet"
                actionLabel="Browser extension"
                actionHref={link("extension")}
            />
        {/if}
    {/await}
</svelte:element>

<style>
    /* Designed cards in place of a column of links (B182). One group per
       category, a grid of cards inside it; the card is the link's target so
       the whole title is the way in, and Forget stays a small control in the
       corner rather than a second thing to read. */
    .hgroup {
        margin: 0 0 var(--s-5);
    }
    .hgroup-title {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        margin: 0 0 var(--s-3);
        padding-bottom: var(--s-2);
        border-bottom: 1px solid var(--line);
    }
    .hgroup-count {
        color: var(--dim);
        font-size: var(--t-sm);
        font-weight: 400;
    }
    .hgrid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
        gap: var(--s-3);
    }
    .hcard {
        position: relative;
        display: grid;
        gap: var(--s-2);
        align-content: start;
        padding: var(--s-3) var(--s-4);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: var(--surface, transparent);
    }
    .hcard:hover {
        border-color: var(--accent);
    }
    .hcard-title {
        color: var(--text);
        font-size: var(--t-md);
        line-height: var(--lh-md);
        font-weight: 600;
        text-decoration: none;
        padding-right: 4.5rem;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .hcard-title:hover {
        color: var(--accent);
    }
    .hcard-meta {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2);
    }
    .hcard :global(.history-forget) {
        position: absolute;
        top: var(--s-2);
        right: var(--s-2);
    }
    .badge.warn {
        background: var(--medium-soft);
        color: var(--medium);
    }
</style>
