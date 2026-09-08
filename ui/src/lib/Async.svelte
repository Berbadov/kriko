<script lang="ts">
    import type { Snippet } from "svelte";
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
</script>

{#await promise}
    {#if skeleton}
        {@render skeleton()}
    {:else}
        <p class="state loading">{loading}</p>
    {/if}
{:then value}
    {@render children(value)}
{:catch error}
    <!-- B72: this used to read "Could not load this view: <exception>", which
         is accurate and useless. A local app has one reader, no terminal and
         nobody to page — whatever this says is the whole remedy they get. -->
    <Failure {error} {retry} />
{/await}
