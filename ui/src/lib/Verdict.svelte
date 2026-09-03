<script lang="ts">
    import type { Mode } from "./mode";
    import type { LookupResult } from "./types";
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
    <p class="verdict-note">{verdict.note}</p>
    {#if mode === "author" && result.flags?.length}
        <p class="flag">flags: {result.flags.join(", ")}</p>
    {/if}
</div>
