<script lang="ts">
    import type { Snippet } from "svelte";

    let {
        promise,
        loading = "Loading…",
        skeleton,
        children,
    }: {
        promise: Promise<any>;
        loading?: string;
        /** The shape of what is coming, for views where that is knowable.
         *  A skeleton is worth the markup only when the layout it stands in for
         *  is stable — otherwise it promises a page that never arrives, which
         *  is worse than the sentence. */
        skeleton?: Snippet;
        children: Snippet<[any]>;
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
    <p class="state error">Could not load this view: {error.message}</p>
{/await}
