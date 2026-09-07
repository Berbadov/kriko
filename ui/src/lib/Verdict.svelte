<script lang="ts">
    import type { Mode } from "./mode";
    import type { LookupResult } from "./types";
    import { handledNote } from "./report";
    import { severityShare, verdictFor } from "./verdict";

    let {
        result,
        handled = [],
        mode = "buyer",
    }: { result: LookupResult; handled?: string[]; mode?: Mode } = $props();

    const verdict = $derived(verdictFor(result, handled));
    const share = $derived(severityShare(verdict.counts));

    // The bar is decoration for a sighted reader and noise for a screen
    // reader unless it says what it means, so it carries the same numbers the
    // headline does as its accessible name.
    // Ten cards and three ticked used to say nothing anywhere. The headline
    // carries "3 handled"; this carries how far that is through the list,
    // which is the thing the reader is actually tracking on a second visit.
    const progress = $derived(handledNote(result, handled));
    const donePercent = $derived(
        verdict.counts.total
            ? Math.round((verdict.counts.handled / verdict.counts.total) * 100)
            : 0,
    );

    const barLabel = $derived(
        `severity mix: ${share.map((s) => `${s.percent}% ${s.severity}`).join(", ")}`,
    );
</script>

<div class="verdict {verdict.tone}">
    <p class="verdict-line">{verdict.headline}</p>
    {#if share.length}
        <div class="verdict-bar" role="img" aria-label={barLabel}>
            {#each share as segment (segment.severity)}
                <span class="seg {segment.severity}" style="width: {segment.percent}%"
                ></span>
            {/each}
        </div>
    {/if}
    {#if progress}
        <p class="verdict-progress">
            <span class="done-bar" role="img" aria-label="{donePercent}% dealt with">
                <span class="done-fill" style="width: {donePercent}%"></span>
            </span>
            <span class="meta">{progress}</span>
        </p>
    {/if}
    <p class="verdict-note">{verdict.note}</p>
    {#if mode === "author" && result.flags?.length}
        <p class="flag">flags: {result.flags.join(", ")}</p>
    {/if}
</div>
