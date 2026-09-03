<script lang="ts">
    import { api } from "./api";
    import ClaimCard from "./ClaimCard.svelte";
    import type { Mode } from "./mode";
    import { claimKey, groupByDomain } from "./report";
    import { hashWith, route } from "./router";
    import type { LookupResult } from "./types";
    import Verdict from "./Verdict.svelte";

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
    <Verdict {result} {handled} {mode} />
    <div class="row no-print">
        <button class="ghost" onclick={() => window.print()}>Print / Save as PDF</button>
        {#if lookupId}
            <a
                class="ghost button-like"
                href={hashWith({ mode: $route.query.mode, left: lookupId }, "compare")}
                >Compare with another</a
            >
        {/if}
    </div>
</header>

<!-- No empty-state paragraph here: the verdict above already renders
     emptyReason(), and printing the same sentence twice was the shape the
     old header had before it carried a verdict at all. -->
{#if result.claims.length}
    <div class="report-body">
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
    </div>
{/if}
