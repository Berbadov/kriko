<script lang="ts">
    import EmptyState from "./lib/EmptyState.svelte";
    import History from "./lib/History.svelte";
    import { initMode, mode } from "./lib/mode";
    import { hashWith, route } from "./lib/router";
    import Sidebar from "./lib/shell/Sidebar.svelte";
    import { isAuthorOnly } from "./lib/shell/nav";
    import Check from "./routes/Check.svelte";
    import Coverage from "./routes/Coverage.svelte";
    import Health from "./routes/Health.svelte";
    import Jobs from "./routes/Jobs.svelte";
    import Overview from "./routes/Overview.svelte";
    import Packs from "./routes/Packs.svelte";
    import Result from "./routes/Result.svelte";
    import Subjects from "./routes/Subjects.svelte";

    // The sidebar panel belongs where a past answer is relevant: beside the
    // form that produces one and beside a result being read. On the History
    // *page* it would be the page twice.
    const WITH_HISTORY = new Set(["check", "result"]);
    const showHistory = $derived(WITH_HISTORY.has($route.name));

    // A view only an author has is not hidden from a buyer who has its link —
    // it is explained, and the switch is one click away in the rail. Silently
    // rendering nothing would look like a broken link.
    const authorOnly = $derived($mode !== "author" && isAuthorOnly($route.name));

    const ready = initMode($route.query.mode);
</script>

<div class="shell">
    <Sidebar mode={$mode} />

    <main class="work" class:with-history={showHistory}>
        <div class="view">
            {#await ready}
                <p class="state loading">Starting…</p>
            {:then}
                {#if authorOnly}
                    <EmptyState
                        title="{$route.name} is an author view"
                        detail="It is real work a pack author does, and none of it helps
                                someone deciding whether to go and look at a listing.
                                Switch to author mode in the rail to open it."
                    />
                {:else if $route.name === "check"}
                    <Check mode={$mode} />
                {:else if $route.name === "overview"}
                    <Overview />
                {:else if $route.name === "subjects"}
                    <Subjects />
                {:else if $route.name === "history"}
                    <h2>History</h2>
                    <History page />
                {:else if $route.name === "coverage"}
                    <Coverage />
                {:else if $route.name === "packs"}
                    <Packs />
                {:else if $route.name === "health"}
                    <Health />
                {:else if $route.name === "jobs"}
                    <Jobs />
                {:else if $route.name === "result"}
                    <!-- Keyed: Result fetches once on init, so moving between two
                         stored results must remount rather than reuse. -->
                    {#key $route.params[0]}
                        <Result lookupId={$route.params[0]} mode={$mode} />
                    {/key}
                {:else}
                    <EmptyState
                        title="No such view: {$route.name}"
                        detail="The link may be from an older version."
                        actionLabel="Go to New check"
                        actionHref={hashWith({ mode: $route.query.mode }, "check")}
                    />
                {/if}
            {/await}
        </div>
        {#if showHistory}
            {#key $route.params[0] ?? $route.name}
                <History />
            {/key}
        {/if}
    </main>
</div>
