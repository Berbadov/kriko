<script lang="ts">
    import Failure from "../lib/Failure.svelte";
    import Report from "../lib/Report.svelte";
    import { ApiError, api } from "../lib/api";
    import type { Mode } from "../lib/mode";
    import type { StoredLookup } from "../lib/types";

    let { lookupId, mode = "buyer" }: { lookupId: string; mode?: Mode } = $props();

    // Derived rather than captured: the App keys this component so a new id
    // remounts it anyway, but a prop that changes must refetch, not go stale.
    //
    // Guarded on a non-empty id: #/result with nothing after it coerced
    // `undefined` into the string "undefined" at the fetch boundary and hit
    // `/api/lookup/undefined`, a 404 and a console error for a screen that
    // has its own empty-history message right below (uicode-1).
    const stored = $derived(lookupId ? api.getLookup(lookupId) : null);
</script>

{#if !lookupId || !stored}
    <p class="state empty">That lookup is no longer in your history.</p>
{:else}
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
        <!-- The 404 above keeps its own sentence because it knows what was
             missing; everything else is generic by status. -->
        <Failure {error} />
    {/if}
{/await}
{/if}
