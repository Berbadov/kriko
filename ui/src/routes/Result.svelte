<script lang="ts">
    import Report from "../lib/Report.svelte";
    import { ApiError, api } from "../lib/api";
    import type { Mode } from "../lib/mode";
    import type { StoredLookup } from "../lib/types";

    let { lookupId, mode = "buyer" }: { lookupId: string; mode?: Mode } = $props();

    // Derived rather than captured: the App keys this component so a new id
    // remounts it anyway, but a prop that changes must refetch, not go stale.
    const stored = $derived(api.getLookup(lookupId));
</script>

{#await stored}
    <p class="state loading">Loading…</p>
{:then result}
    <Report
        result={result.response}
        {mode}
        {lookupId}
        heading={result.label}
    />
    <p class="meta">Asked {result.created_at} · {result.source}</p>
{:catch error}
    {#if error instanceof ApiError && error.status === 404}
        <p class="state empty">That lookup is no longer in your history.</p>
    {:else}
        <p class="state error">Could not load this view: {error.message}</p>
    {/if}
{/await}
