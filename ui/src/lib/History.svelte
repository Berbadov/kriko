<script lang="ts">
    import EmptyState from "./EmptyState.svelte";
    import { ApiError, api } from "./api";
    import { count } from "./plural";
    import { localTime, sourceWord } from "./report";
    import { hashWith, navigate, route } from "./router";
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

    // hashWith, not toHash: a bare link dropped ?mode, so an author clicking a
    // recent result landed in buyer mode with no indication why.
    const link = (name: string, ...params: string[]) =>
        hashWith({ mode: $route.query.mode }, name, ...params);

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

    async function forget(item: HistoryItem) {
        notice = "";
        try {
            await api.forget(item.lookup_id);
        } catch (e) {
            // Already gone is not a failure the reader caused (check-16): a
            // second window, or the extension, may have forgotten it first.
            // Any other error stays on screen rather than silently keeping a
            // dead row in the list.
            if (!(e instanceof ApiError && e.status === 404)) {
                notice = "Could not forget that check — try again.";
                return;
            }
        }
        // The open Result for this exact check is a stale page the moment its
        // row is gone (check-32): its Handled boxes and notes would still
        // post, against a lookup the server no longer has.
        if ($route.name === "result" && $route.params[0] === item.lookup_id) {
            navigate("check");
            return;
        }
        await refresh();
    }

    const ready = refresh();
</script>

<svelte:element
    this={page ? "section" : "aside"}
    class={page ? "history page" : "history"}
>
    {#if !page}<h3>Recent</h3>{/if}
    {#if notice}<p class="state">{notice}</p>{/if}
    {#await ready then}
        {#if items.length}
            {#if page}
                <p class="meta">
                    <a href={link("compare")}>Compare two of these →</a>
                </p>
            {/if}
            <ul>
                {#each items as item (item.lookup_id)}
                    <li>
                        <a class="history-title" href={link("result", item.lookup_id)}
                            >{item.label}</a
                        >
                        <span class="meta"
                            >{count(item.claim_count, "known risk")} · {sourceWord(item.source)}{#if page}
                                {" · "}{localTime(item.created_at)}{/if}</span
                        >
                        <!-- `small`, and titled rather than captioned in the rail: one
                             full-size button per row turned a seven-item list into a
                             column of seven buttons taller than the screen it sat
                             beside. The word stays for the page view, where there is
                             room for it and no other control to confuse it with. -->
                        <button
                            class="ghost small history-forget"
                            title="Forget this check"
                            onclick={() => forget(item)}>Forget</button
                        >
                    </li>
                {/each}
            </ul>
            {#if page && hasMore}
                <button class="ghost" onclick={showOlder}>Show older</button>
            {/if}
        {:else}
            <EmptyState
                title="Nothing asked yet"
                detail="Every check you run is kept here so you can reopen it, link it, or
                        compare two listings."
                actionLabel="Run a check"
                actionHref={link("check")}
            />
        {/if}
    {/await}
</svelte:element>
