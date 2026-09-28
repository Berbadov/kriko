<script lang="ts">
    import { untrack, type Snippet } from "svelte";
    import Failure from "./Failure.svelte";

    let {
        promise,
        loading = "Loading…",
        skeleton,
        children,
        retry,
    }: {
        promise: Promise<any>;
        loading?: string;
        /** The shape of what is coming, for views where that is knowable.
         *  A skeleton is worth the markup only when the layout it stands in for
         *  is stable — otherwise it promises a page that never arrives, which
         *  is worse than the sentence. */
        skeleton?: Snippet;
        children: Snippet<[any]>;
        /** Passed through to Failure. Optional, because most views build
         *  their promise as a const and making it retryable is a change to
         *  the view, not to this component. */
        retry?: () => void;
    } = $props();

    /* Not `{#await}`, on purpose. An await block drops back to its pending
     * branch every time `promise` is replaced, which unmounts everything
     * rendered from the last answer: a view that refreshes after a change —
     * pick an agent in a dropdown, press Retry — blanked to "Loading…" and
     * came back with every <details> shut and the dropdown the reader was
     * using gone from under the pointer. The screen walker found it as a
     * select that could not be chosen twice. So the last answer stays on
     * screen until the next one lands, and an answer to a promise that has
     * since been replaced is dropped rather than painted over a newer one. */
    type Outcome = { ok: true; value: any } | { ok: false; error: unknown };
    let outcome = $state<Outcome | null>(null);

    $effect(() => {
        const current = promise;
        let live = true;
        // After a failure, a retry shows the sentence rather than the old error.
        untrack(() => {
            if (outcome && !outcome.ok) outcome = null;
        });
        current.then(
            (value) => live && (outcome = { ok: true, value }),
            (error) => live && (outcome = { ok: false, error }),
        );
        return () => {
            live = false;
        };
    });
</script>

{#if outcome?.ok}
    {@render children(outcome.value)}
{:else if outcome}
    <!-- B72: this used to read "Could not load this view: <exception>", which
         is accurate and useless. A local app has one reader, no terminal and
         nobody to page — whatever this says is the whole remedy they get. -->
    <Failure error={outcome.error} {retry} />
{:else if skeleton}
    {@render skeleton()}
{:else}
    <p class="state loading">{loading}</p>
{/if}
