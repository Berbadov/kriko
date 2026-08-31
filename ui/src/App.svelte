<script lang="ts">
    import History from "./lib/History.svelte";
    import { route, toHash } from "./lib/router";
    import Analyze from "./routes/Analyze.svelte";
    import Ask from "./routes/Ask.svelte";
    import Browse from "./routes/Browse.svelte";
    import Coverage from "./routes/Coverage.svelte";
    import Dashboard from "./routes/Dashboard.svelte";
    import Health from "./routes/Health.svelte";
    import Packs from "./routes/Packs.svelte";
    import Result from "./routes/Result.svelte";

    const VIEWS = [
        { name: "ask", label: "Ask" },
        { name: "analyze", label: "Analyze" },
        { name: "dashboard", label: "Dashboard" },
        { name: "browse", label: "Browse" },
        { name: "coverage", label: "Coverage" },
        { name: "health", label: "Health" },
        { name: "packs", label: "Packs" },
    ];

    // The sidebar belongs where a past answer is relevant: beside the forms
    // that produce one and beside a result being read. It would be noise on
    // Packs or Coverage.
    const WITH_HISTORY = new Set(["ask", "analyze", "result"]);
    const showHistory = $derived(WITH_HISTORY.has($route.name));
</script>

<header>
    <h1>Kriko</h1>
    <span class="sub">local product knowledge</span>
    <nav>
        {#each VIEWS as view (view.name)}
            <a
                class="tab"
                class:active={$route.name === view.name}
                href={toHash(view.name)}>{view.label}</a
            >
        {/each}
    </nav>
</header>

<main class:with-history={showHistory}>
    <section class="active">
        {#if $route.name === "ask"}
            <Ask />
        {:else if $route.name === "analyze"}
            <Analyze />
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
        {:else if $route.name === "result"}
            <!-- Keyed: Result fetches once on init, so moving between two
                 stored results must remount rather than reuse. -->
            {#key $route.params[0]}
                <Result lookupId={$route.params[0]} />
            {/key}
        {:else}
            <h2>{$route.name}</h2>
        {/if}
    </section>
    {#if showHistory}
        {#key $route.params[0] ?? $route.name}
            <History />
        {/key}
    {/if}
</main>
