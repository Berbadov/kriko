<script lang="ts">
    import { api } from "./api";
    import type { Scale } from "./types";

    /* How deep this run goes — one control, wherever a run is started.
     *
     * The dial existed. `app/scale.py` has had four presets, an estimate per
     * preset and a per-run cap since it was written, and `/api/research` has
     * taken a `scale` field for as long. What it never had was anywhere to
     * *press*: the only screen offering depth was the benchmark, and it
     * offered a hardcoded copy of three of the four presets. So the reader's
     * "I don't want my agent to search 30 sources, maybe I want 3" was
     * already implemented everywhere except the place they stand.
     *
     * Two decisions worth keeping:
     *
     * **The numbers come from the server.** Not one of them is written here.
     * The benchmark's copy is exactly the hand-maintained correspondence this
     * repository keeps catching after it has already gone stale, and a dial
     * whose label says "3 sources" while the engine reads seven is worse than
     * no dial — it teaches the reader the control is decorative.
     *
     * **The knobs stay reachable.** `custom` is not a fifth mode with its own
     * code path; it is the preset whose numbers are all zero, so the field
     * below lands as an override on any position. Somebody who wants five
     * sources rather than three or seven can have five, without routing
     * around the control to get it.
     */
    let {
        scale = $bindable(""),
        maxDocuments = $bindable(0),
        /** The count this dial actually resolves to — the override if there
         *  is one, otherwise the chosen preset's. Written, never read: a
         *  caller that sends a *number* rather than a preset name (the
         *  benchmark does, because a run has to record what it really read)
         *  binds this and ignores the two above. */
        resolved = $bindable(0),
        disabled = false,
        /** Shown under the chips. Each caller multiplies the per-subject cost
         *  differently — an agenda run by its row count, the benchmark by
         *  cases times repetitions — and only the caller knows by how much. */
        multiplier = 1,
        label = "How deep",
    }: {
        scale?: string;
        maxDocuments?: number;
        resolved?: number;
        disabled?: boolean;
        multiplier?: number;
        label?: string;
    } = $props();

    let offered = $state<Scale[]>([]);
    /* Best-effort, like every other secondary fetch on these screens: a
     * `/api/scales` that fails costs the reader the dial and never the button
     * it sits beside. An empty list renders nothing at all and the run goes at
     * the server's default — which is what every run did before this existed. */
    api.scales()
        .then((data) => {
            offered = data.scales ?? [];
            if (!scale) scale = data.default ?? "";
        })
        .catch(() => (offered = []));

    const chosen = $derived(offered.find((one) => one.id === scale));
    const isCustom = $derived(chosen?.max_documents === 0);
    /* What will actually be read, which is not always what the preset says:
     * an explicit count wins, and `custom` has no count of its own. */
    const sources = $derived(maxDocuments || chosen?.max_documents || 0);
    // Pushed back out so a caller sending a count does not have to re-derive
    // the same precedence rule and get it subtly different.
    $effect(() => {
        resolved = sources;
    });

    function pick(one: Scale) {
        scale = one.id;
        // A preset replaces the override rather than sitting under it.
        // Leaving a stale number behind is how a reader presses "Quick" and
        // gets fifteen sources — the control appearing to work and not.
        if (one.max_documents) maxDocuments = 0;
    }

    const money = (usd: number | null) =>
        usd === null || usd === undefined ? "" : `~$${(usd * multiplier).toFixed(2)}`;
</script>

{#if offered.length}
    <fieldset class="scale">
        <legend>{label}</legend>
        <div class="chips" role="group" aria-label={label}>
            {#each offered as one (one.id)}
                <button
                    type="button"
                    {disabled}
                    aria-pressed={scale === one.id}
                    title={one.note}
                    onclick={() => pick(one)}>{one.label}</button
                >
            {/each}
        </div>

        {#if isCustom || maxDocuments}
            <label class="sources">
                Sources
                <input
                    type="number"
                    min="1"
                    max="50"
                    {disabled}
                    value={maxDocuments || ""}
                    placeholder={String(chosen?.max_documents || 7)}
                    onchange={(event) =>
                        (maxDocuments = Math.max(
                            0,
                            Math.min(50, Number(event.currentTarget.value) || 0),
                        ))}
                />
            </label>
        {/if}

        <p class="meta">
            {chosen?.note ?? ""}
            {#if sources}
                <br />Up to {sources} source(s) per subject{multiplier > 1
                    ? ` × ${multiplier}`
                    : ""}.
            {/if}
            {#if chosen && chosen.usd !== null}
                {money(chosen.usd)} on the paid plane — measured here, not a price
                list.
            {:else if chosen}
                Nothing of this shape has been measured here yet, so there is no
                honest estimate to show.
            {/if}
            {#if chosen?.cap_usd}
                Stops at ${chosen.cap_usd.toFixed(2)}.
            {/if}
        </p>
        {#if !isCustom && !maxDocuments}
            <button
                type="button"
                class="ghost"
                {disabled}
                onclick={() => (maxDocuments = chosen?.max_documents || 7)}
                >Set an exact number</button
            >
        {/if}
    </fieldset>
{/if}

<style>
    .scale {
        margin-block: var(--s-3);
    }
    .sources {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        margin-block-start: var(--s-2);
    }
    .sources input {
        width: 5rem;
    }
</style>
