<script lang="ts">
    import { remedyFor } from "./failure";
    import { hashWith, route } from "./router";

    // One component for every failed view, so a new view cannot ship with
    // worse error copy than the rest — it gets this by using Async at all.
    let {
        error,
        retry,
    }: {
        error: unknown;
        /** Given only where re-running is a one-line change. Absent means no
         *  button rather than a button that reloads the window and loses the
         *  reader's place. */
        retry?: () => void;
    } = $props();

    const remedy = $derived(remedyFor(error));
    let showDetail = $state(false);
</script>

<div class="failure" role="alert">
    <p class="state error">{remedy.headline}</p>
    <p>{remedy.next}</p>
    <div class="row">
        {#if retry && remedy.retryable}
            <button onclick={retry}>Try again</button>
        {/if}
        {#if remedy.route}
            <a class="tab" href={hashWith({ mode: $route.query.mode }, remedy.route)}>
                {remedy.routeLabel}
            </a>
        {/if}
        <!-- The exception is kept and folded away rather than dropped: the
             remedy is what the reader needs, and the exception is what we
             need when the remedy did not work. -->
        <button class="ghost" onclick={() => (showDetail = !showDetail)}>
            {showDetail ? "Hide the details" : "Show the details"}
        </button>
    </div>
    {#if showDetail}
        <pre>{remedy.technical}</pre>
    {/if}
</div>
