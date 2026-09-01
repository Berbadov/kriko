<script lang="ts">
    import type { Snippet } from "svelte";

    let {
        promise,
        loading = "Loading…",
        children,
    }: {
        promise: Promise<any>;
        loading?: string;
        children: Snippet<[any]>;
    } = $props();
</script>

{#await promise}
    <p class="state loading">{loading}</p>
{:then value}
    {@render children(value)}
{:catch error}
    <p class="state error">Could not load this view: {error.message}</p>
{/await}
