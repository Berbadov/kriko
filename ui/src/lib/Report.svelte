<script lang="ts">
    import { api } from "./api";
    import ClaimCard from "./ClaimCard.svelte";
    import type { Mode } from "./mode";
    import { confidenceNote, claimKey, emptyReason, groupByDomain } from "./report";
    import type { LookupResult } from "./types";

    let {
        result,
        mode = "buyer",
        lookupId = "",
        heading = "",
    }: {
        result: LookupResult;
        mode?: Mode;
        lookupId?: string;
        heading?: string;
    } = $props();

    const groups = $derived(groupByDomain(result.claims));
    const worst = $derived(
        result.claims.filter((c) => c.severity === "high").length,
    );

    let handled = $state<string[]>([]);

    // Triage is per stored answer, so an unsaved result simply has none. The
    // component renders identically either way rather than growing a second
    // read-only variant.
    $effect(() => {
        if (!lookupId) return;
        api.checked(lookupId)
            .then((r) => (handled = r.checked ?? []))
            .catch(() => {});
    });

    async function check(key: string, next: boolean) {
        handled = next ? [...handled, key] : handled.filter((k) => k !== key);
        if (!lookupId) return;
        try {
            handled = (await api.setChecked(lookupId, key, next)).checked ?? handled;
        } catch {
            // The optimistic update above stands. A failed note is not worth
            // yanking a checkbox back out from under the reader's cursor.
        }
    }
</script>

<header class="report-head">
    {#if heading}<h2>{heading}</h2>{/if}
    <p class="meta">{confidenceNote(result)}</p>
    {#if result.claims.length}
        <p class="lede">
            {result.claims.length} known risk{result.claims.length === 1 ? "" : "s"}
            {#if worst}
                · <strong class="high-count">{worst} serious</strong>
            {/if}
            {#if handled.length}
                · {handled.length} handled
            {/if}
        </p>
    {/if}
    {#if mode === "author" && result.flags?.length}
        <p class="flag">flags: {result.flags.join(", ")}</p>
    {/if}
</header>

{#if !result.claims.length}
    <p class="state {result.coverage === 'NOT_MATCHED' ? 'no-match' : 'unknown'}">
        {emptyReason(result)}
    </p>
{:else}
    {#each groups as group (group.domain)}
        <section class="group">
            <h3 class="group-head">{group.domain}</h3>
            {#each group.claims as claim (claimKey(claim))}
                <ClaimCard
                    {claim}
                    {mode}
                    checked={handled.includes(claimKey(claim))}
                    onCheck={(next) => check(claimKey(claim), next)}
                />
            {/each}
        </section>
    {/each}
{/if}
