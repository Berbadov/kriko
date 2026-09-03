<script lang="ts">
    import EmptyState from "./EmptyState.svelte";
    import { api } from "./api";
    import { hashWith, route } from "./router";
    import type { HistoryItem } from "./types";

    let { page = false }: { page?: boolean } = $props();

    let items = $state<HistoryItem[]>([]);

    // hashWith, not toHash: a bare link dropped ?mode, so an author clicking a
    // recent result landed in buyer mode with no indication why.
    const link = (name: string, ...params: string[]) =>
        hashWith({ mode: $route.query.mode }, name, ...params);

    async function refresh() {
        items = (await api.history()).items;
    }

    async function forget(item: HistoryItem) {
        await api.forget(item.lookup_id);
        await refresh();
    }

    const ready = refresh();
</script>

<svelte:element
    this={page ? "section" : "aside"}
    class={page ? "history page" : "history"}
>
    {#if !page}<h3>Recent</h3>{/if}
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
                        <a href={link("result", item.lookup_id)}>{item.label}</a>
                        <span class="meta"
                            >{item.claim_count} claim(s) · {item.source}{#if page} ·
                                {item.created_at}{/if}</span
                        >
                        <button class="ghost" onclick={() => forget(item)}>Forget</button>
                    </li>
                {/each}
            </ul>
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
