<script lang="ts">
    import { route, toHash } from "./lib/router";

    const VIEWS = [
        { name: "ask", label: "Ask" },
        { name: "analyze", label: "Analyze" },
        { name: "dashboard", label: "Dashboard" },
        { name: "browse", label: "Browse" },
        { name: "coverage", label: "Coverage" },
        { name: "health", label: "Health" },
        { name: "packs", label: "Packs" },
    ];
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

<main>
    <section class="active"><h2>{$route.name}</h2></section>
</main>
