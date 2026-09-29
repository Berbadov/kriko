<script lang="ts">
    import Failure from "../lib/Failure.svelte";
    import Report from "../lib/Report.svelte";
    import { ApiError, api } from "../lib/api";
    import { onKnowledgeChange } from "../lib/knowledge";
    import type { Mode } from "../lib/mode";
    import { claimKey, localTime, sourceWord } from "../lib/report";
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

    /* B152.4: "a card added by the agent, we instantly see the new card".
     * While this answer is open, a write to the knowledge from anywhere — the
     * reader's agent over MCP, a research job — asks for the saved question
     * to be answered again, in place. What arrived is marked New. */
    let live = $state<StoredLookup | null>(null);
    let fresh = $state<string[]>([]);

    $effect(() => {
        if (!lookupId || !stored) return;
        const id = lookupId;
        const first = stored;
        live = null;
        fresh = [];
        let busy = false;
        return onKnowledgeChange(async () => {
            if (busy) return;
            busy = true;
            try {
                const shown = live ?? (await first);
                const before = new Set(shown.response.claims.map(claimKey));
                const next = await api.refreshLookup(id);
                if (!next.refreshed) return;
                const added = next.response.claims
                    .map(claimKey)
                    .filter((key) => !before.has(key));
                fresh = [...new Set([...fresh, ...added])];
                live = next;
            } catch {
                // The answer on screen stays; the next change tries again.
            } finally {
                busy = false;
            }
        });
    });
</script>

{#if !lookupId || !stored}
    <p class="state empty">That lookup is no longer in your history.</p>
{:else}
{#await stored}
    <p class="state loading">Loading…</p>
{:then first}
    {@const result = live ?? first}
    <Report
        result={result.response}
        {mode}
        {lookupId}
        heading={result.label}
        {fresh}
    />
    <p class="meta">
        Asked {localTime(result.created_at)} · {sourceWord(result.source)}
        {#if result.source === "analyze" && typeof result.request.url === "string"}
            · <a href={result.request.url} target="_blank" rel="noopener">Open the listing</a>
        {/if}
    </p>
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
