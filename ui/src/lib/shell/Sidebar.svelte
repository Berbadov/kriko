<script lang="ts">
    import { tick } from "svelte";
    import { MODES, setMode, type Mode } from "../mode";
    import { hashWith, route } from "../router";
    import { rowFor } from "./mark";
    import NavGroup from "./NavGroup.svelte";
    import { groupsFor, resolve } from "./nav";

    let { mode }: { mode: Mode } = $props();

    const groups = $derived(groupsFor(mode));

    /* The rail highlights the screen that is *rendered*, which is not always
     * the screen that was asked for. `#/coverage` renders Knowledge's gaps
     * lens — App.svelte resolves that, and until this line the rail did not,
     * so arriving from the browser extension's link lit no row at all and the
     * marker switched off. One resolve, read by the rows and the marker
     * alike. */
    const current = $derived(resolve($route.name).name);

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

    /* Measured after the flush, against the route rather than against a class.
     *
     * Both halves were bugs. `querySelector(".nav-link.active")` asked a
     * *child* component's markup a question at a moment when Svelte had not
     * yet updated it — parent effects run before child template updates — so
     * the row measured was the one the reader had just left, and the marker
     * lived one navigation behind the app. `rowFor` takes the route instead,
     * which is the value we already hold and which cannot be stale
     * (lib/shell/mark.ts).
     *
     * `tick()` covers the other half: a mode switch adds and removes whole
     * groups, so the row for the new route may not have mounted yet. After
     * the tick, every child's markup has landed and `offsetTop` means
     * something. The `live` flag drops a measurement whose navigation has
     * already been superseded — two fast clicks must not race.
     */
    $effect(() => {
        // Tracked: the resolved route, and the group list — switching mode
        // adds and removes whole groups, which moves every row below them.
        const target = current;
        void groups;
        const nav = navEl;
        if (!nav) {
            marked = false;
            return;
        }
        let live = true;
        void tick().then(() => {
            if (!live) return;
            const el = rowFor(nav, target);
            if (!el) {
                marked = false;
                return;
            }
            // offsetTop against `.rail-nav`, which is the positioned ancestor —
            // so the marker scrolls with the rows if the rail ever does.
            markTop = el.offsetTop;
            markHeight = el.offsetHeight;
            marked = markHeight > 0;
        });
        return () => {
            live = false;
        };
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
                <NavGroup {group} {current} {href} />
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
