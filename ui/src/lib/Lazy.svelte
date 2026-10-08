<script lang="ts">
    import { untrack, type Component } from "svelte";
    import Failure from "./Failure.svelte";
    import JackMark from "./kriko/JackMark.svelte";

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
    <p class="state loading loading-mark"><JackMark />Starting…</p>
{:then mod}
    {@const Screen = mod.default}
    <Screen {...props} />
{:catch error}
    <Failure {error} />
{/await}
