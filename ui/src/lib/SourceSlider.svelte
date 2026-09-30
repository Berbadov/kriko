<script lang="ts">
    import Icon from "./Icon.svelte";
    import { api } from "./api";
    import { count as plural } from "./plural";
    import { estimateFor, startingCount } from "./sources";
    import type { Scale } from "./types";

    /* How many sources a run may read: one slider, the count and an estimate.
     *
     * It replaces four preset chips and a hidden number input (`Scale`, which
     * Brief and the benchmark still use) on the Run screen. The numbers come
     * from `/api/scales`, the server's own table: the estimate is a measured
     * rate, not a price list typed here, and the starting position is the
     * server's default. `maxSources` is the ceiling the request accepts
     * (`AuthorRequest.max_documents`), so the thumb cannot reach a value the
     * server would then refuse.
     */
    let {
        value = $bindable(0),
        disabled = false,
        maxSources = 50,
    }: { value?: number; disabled?: boolean; maxSources?: number } = $props();

    let scales = $state<Scale[]>([]);
    api.scales()
        .then((data) => {
            scales = data.scales ?? [];
            if (!value) value = startingCount(scales, data.default ?? "");
        })
        .catch(() => {
            // Best-effort like the other secondary fetches: without the table
            // the slider still works, at a fixed start and with no estimate.
            if (!value) value = startingCount([], "");
        });

    const usd = $derived(estimateFor(scales, value));
</script>

<div class="sources">
    <label for="sources-range" class="cap"><Icon name="fetch" size={14} /> Sources</label>
    <input
        id="sources-range"
        type="range"
        min="1"
        max={maxSources}
        step="1"
        {disabled}
        bind:value
        aria-valuetext={plural(value, "source")}
    />
    <output class="count" for="sources-range">{value}</output>
    <span
        class="estimate"
        title="Measured on this machine for the paid plane. A coding agent you already have costs no API fee."
    >
        {usd === null ? "No estimate yet" : `~$${usd.toFixed(2)}`}
    </span>
</div>

<style>
    .sources {
        display: grid;
        grid-template-columns: auto minmax(8rem, 1fr) 2.5rem auto;
        align-items: center;
        gap: var(--s-3);
        margin-block-start: var(--s-3);
    }
    .cap {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.8rem;
        color: var(--ink-2);
    }
    input[type="range"] {
        accent-color: var(--accent);
        width: 100%;
    }
    .count {
        font-variant-numeric: tabular-nums;
        text-align: end;
        color: var(--text);
    }
    .estimate {
        color: var(--dim);
        font-size: var(--t-xs);
        white-space: nowrap;
    }
    @media (max-width: 34rem) {
        .sources {
            grid-template-columns: auto 1fr 2.5rem;
        }
        .estimate {
            grid-column: 1 / -1;
        }
    }
</style>
