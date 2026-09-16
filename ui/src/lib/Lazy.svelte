<script lang="ts">
    import { untrack, type Component } from "svelte";
    import Failure from "./Failure.svelte";

    let {
        loader,
        props = {},
    }: {
        loader: () => Promise<{ default: Component<any> }>;
        props?: Record<string, unknown>;
    } = $props();

    const promise = untrack(() => loader());
</script>

{#await promise}
    <p class="state loading">Starting…</p>
{:then mod}
    {@const Screen = mod.default}
    <Screen {...props} />
{:catch error}
    <Failure {error} />
{/await}
