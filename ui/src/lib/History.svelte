<script lang="ts">
    import { api } from "./api";
    import { toHash } from "./router";
    import type { HistoryItem } from "./types";

    let items = $state<HistoryItem[]>([]);

    async function refresh() {
        items = (await api.history()).items;
    }

    async function forget(item: HistoryItem) {
        await api.forget(item.lookup_id);
        await refresh();
    }

    const ready = refresh();
</script>

<aside class="history">
    <h3>Recent</h3>
    {#await ready then}
        {#if items.length}
            <ul>
                {#each items as item (item.lookup_id)}
                    <li>
                        <a href={toHash("result", item.lookup_id)}>{item.label}</a>
                        <span class="meta">{item.claim_count} claim(s) · {item.source}</span>
                        <button class="ghost" onclick={() => forget(item)}>Forget</button>
                    </li>
                {/each}
            </ul>
        {:else}
            <p class="state empty">Nothing asked yet.</p>
        {/if}
    {/await}
</aside>
