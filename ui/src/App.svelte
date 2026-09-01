<script lang="ts">
    import History from "./lib/History.svelte";
    import { MODES, initMode, mode, setMode, type Mode } from "./lib/mode";
    import { hashWith, route } from "./lib/router";
    import Browse from "./routes/Browse.svelte";
    import Check from "./routes/Check.svelte";
    import Coverage from "./routes/Coverage.svelte";
    import Dashboard from "./routes/Dashboard.svelte";
    import Health from "./routes/Health.svelte";
    import Jobs from "./routes/Jobs.svelte";
    import Packs from "./routes/Packs.svelte";
    import Result from "./routes/Result.svelte";

    // Buyer mode is two screens on purpose. Every operator view below is real
    // work a pack author does, and none of it helps someone deciding whether
    // to go and look at a listing.
    const BUYER_VIEWS = [{ name: "check", label: "Check" }];
    const AUTHOR_VIEWS = [
        { name: "check", label: "Check" },
        { name: "dashboard", label: "Dashboard" },
        { name: "browse", label: "Browse" },
        { name: "coverage", label: "Coverage" },
        { name: "jobs", label: "Jobs" },
        { name: "health", label: "Health" },
        { name: "packs", label: "Packs" },
    ];

    const views = $derived($mode === "author" ? AUTHOR_VIEWS : BUYER_VIEWS);

    // The sidebar belongs where a past answer is relevant: beside the form
    // that produces one and beside a result being read.
    const WITH_HISTORY = new Set(["check", "result"]);
    const showHistory = $derived(WITH_HISTORY.has($route.name));

    const link = (name: string, ...params: string[]) =>
        hashWith({ mode: $route.query.mode }, name, ...params);

    // A view only an author has is not hidden from a buyer who has its link —
    // it is *explained*, and the reader is offered the switch. Silently
    // rendering nothing would look like a broken link.
    const authorOnly = $derived(
        $mode !== "author" && AUTHOR_VIEWS.some((v) => v.name === $route.name)
            && !BUYER_VIEWS.some((v) => v.name === $route.name),
    );

    const ready = initMode($route.query.mode);
</script>

<header>
    <h1>Kriko</h1>
    <span class="sub">local product knowledge</span>
    <nav>
        {#each views as view (view.name)}
            <a class="tab" class:active={$route.name === view.name} href={link(view.name)}
                >{view.label}</a
            >
        {/each}
        <span class="modes" role="group" aria-label="Mode">
            {#each MODES as candidate (candidate)}
                <button
                    class="tab"
                    class:active={$mode === candidate}
                    onclick={() => setMode(candidate as Mode)}>{candidate}</button
                >
            {/each}
        </span>
    </nav>
</header>

<main class:with-history={showHistory}>
    <div class="view">
        {#await ready then}
            {#if authorOnly}
                <p class="state unknown">
                    <strong>{$route.name} is an author view.</strong>
                    <span>Switch to author mode to open it.</span>
                </p>
            {:else if $route.name === "check"}
                <Check mode={$mode} />
            {:else if $route.name === "dashboard"}
                <Dashboard />
            {:else if $route.name === "coverage"}
                <Coverage />
            {:else if $route.name === "packs"}
                <Packs />
            {:else if $route.name === "browse"}
                <Browse />
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
                <p class="state unknown">No such view: {$route.name}</p>
            {/if}
        {/await}
    </div>
    {#if showHistory}
        {#key $route.params[0] ?? $route.name}
            <History />
        {/key}
    {/if}
</main>
