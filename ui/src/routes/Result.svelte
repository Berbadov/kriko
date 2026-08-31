<script lang="ts">
    import ClaimCard from "../lib/ClaimCard.svelte";
    import { ApiError, api } from "../lib/api";
    import type { StoredLookup } from "../lib/types";

    let { lookupId }: { lookupId: string } = $props();

    const load = async (): Promise<StoredLookup> => api.getLookup(lookupId);
    const stored = load();
</script>

{#await stored}
    <p class="state loading">Loading…</p>
{:then result}
    <h2>{result.label}</h2>
    <p class="meta">
        {result.source} · {result.created_at} · {result.response.method}
        {#if result.response.coverage} · {result.response.coverage}{/if}
    </p>
    {#if result.response.claims.length}
        {#each result.response.claims as claim}<ClaimCard {claim} detailed />{/each}
    {:else}
        <p class="state empty">This lookup returned no claims.</p>
    {/if}
{:catch error}
    {#if error instanceof ApiError && error.status === 404}
        <p class="state empty">That lookup is no longer in your history.</p>
    {:else}
        <p class="state error">Could not load this view: {error.message}</p>
    {/if}
{/await}
