<script lang="ts">
    import { MODES, setMode, type Mode } from "../mode";
    import { hashWith, route } from "../router";
    import NavGroup from "./NavGroup.svelte";
    import { groupsFor } from "./nav";

    let { mode }: { mode: Mode } = $props();

    const groups = $derived(groupsFor(mode));

    // Every rail link carries the mode, and it comes from the prop rather than
    // from the URL: the URL may legitimately omit it — a first visit reads the
    // remembered setting — and a link that drops it looks like the app
    // switching modes on its own.
    const href = (name: string) => hashWith({ mode }, name);

    /* One marker that moves, rather than a border that appears.
     *
     * Fourteen links each growing their own left border on activation reads
     * as fourteen things blinking; a single bar sliding from the old row to
     * the new one reads as one object moving, which is what actually
     * happened. It is measured rather than declared because the rows are not
     * a fixed height — a group heading appears between some of them.
     *
     * Additive on purpose: `.nav-link.active` keeps its own background, so if
     * measurement returns zero (a headless render, a font that has not landed
     * yet) the active row is still obviously the active row and only the
     * flourish is missing.
     */
    let navEl = $state<HTMLElement | undefined>();
    let markTop = $state(0);
    let markHeight = $state(0);
    let marked = $state(false);

    $effect(() => {
        // Tracked: the route, and the group list — switching mode adds and
        // removes whole groups, which moves every row below them.
        const current = $route.name;
        void groups;
        if (!navEl) {
            marked = false;
            return;
        }
        const el = navEl.querySelector<HTMLElement>(".nav-link.active");
        if (!el) {
            marked = false;
            return;
        }
        // offsetTop against `.rail-nav`, which is the positioned ancestor —
        // so the marker scrolls with the rows if the rail ever does.
        markTop = el.offsetTop;
        markHeight = el.offsetHeight;
        marked = markHeight > 0;
        void current;
    });
</script>

<aside class="rail">
    <a class="brand" href={href("check")}>
        <!-- The extension's toolbar icon, the same file the installer's
             app icon is rendered from. The reader met this product in a
             browser toolbar; a different mark here reads as a different
             tool. -->
        <!-- `/static/`, not `/`: Vite's base is /static/ because FastAPI
             mounts StaticFiles there, so a root-relative path to a
             public/ asset falls through to the SPA catch-all and the mark
             renders as a broken image. Guarded by public-assets.test.ts. -->
        <img class="mark" src="/static/mark.svg" alt="" width="28" height="28" />
        <span class="brand-text">
            <strong>Kriko</strong>
            <span class="meta">local product knowledge</span>
        </span>
    </a>

    <nav class="rail-nav" bind:this={navEl}>
        <span
            class="nav-mark"
            class:on={marked}
            style="--mark-top: {markTop}px; --mark-height: {markHeight}px"
            aria-hidden="true"
        ></span>
        {#each groups as group, index (group.title)}
            <div class="nav-slot" style="--slot: {index}">
                <NavGroup {group} current={$route.name} {href} />
            </div>
        {/each}
    </nav>

    <div class="rail-foot">
        <span class="modes" role="group" aria-label="Mode">
            {#each MODES as candidate (candidate)}
                <button
                    class="tab"
                    class:active={mode === candidate}
                    onclick={() => setMode(candidate as Mode)}>{candidate}</button
                >
            {/each}
        </span>
    </div>
</aside>
