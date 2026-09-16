<script lang="ts">
    import { onMount } from "svelte";
    import { MODES, setMode, type Mode } from "../mode";
    import { hashWith, route } from "../router";
    import { figures } from "./figures";
    import { readings, watch } from "./instruments";
    import NavGroup from "./NavGroup.svelte";
    import { groupsFor, resolve } from "./nav";

    let { mode }: { mode: Mode } = $props();

    const groups = $derived(groupsFor(mode));

    /* The rail's own numbers. Started here rather than in App.svelte because
     * the rail is the only thing that reads them — a clock owned by whatever
     * happens to mount first is a clock that stops when that thing unmounts.
     * `watch` is idempotent and returns its own stop, so a remount does not
     * leave two running. */
    onMount(watch);

    const reading = $derived(figures($readings));

    /* The rail highlights the screen that is *rendered*, which is not always
     * the screen that was asked for. `#/coverage` renders Knowledge's gaps
     * lens — App.svelte resolves that, and until this line the rail did not,
     * so arriving from the browser extension's link lit no row at all. One
     * resolve, read by every row's `.active` class, is what keeps them
     * agreeing with what is actually on screen. */
    const current = $derived(resolve($route.name).name);

    // Every rail link carries the mode, and it comes from the prop rather than
    // from the URL: the URL may legitimately omit it — a first visit reads the
    // remembered setting — and a link that drops it looks like the app
    // switching modes on its own.
    const href = (name: string) => hashWith({ mode }, name);

    /* The active row used to carry a second, *measured* indicator — a bar
     * this component positioned in JS from `rowFor(...).offsetTop` after
     * `tick()` (see the deleted `lib/shell/mark.ts`). That fixed the bug it
     * was built for — a stale `.active` class read from a not-yet-updated
     * child — and then grew a second class of bug nothing here ever tested
     * for, because every failure mode was a layout timing problem and jsdom
     * has no layout:
     *
     *   - first paint measured the fallback font's metrics, because
     *     `fonts.css` uses `font-display: swap` on purpose (text beats no
     *     text) — the bar landed at the fallback-font offset and never
     *     moved again until the next navigation retriggered the effect;
     *   - the effect's dependencies were the route and the group list, not
     *     the window, so crossing the `(max-height: 820px)` breakpoint —
     *     which changes `.nav-link` padding and therefore every row's
     *     height — left the bar sized for the padding that was current when
     *     the reader last navigated, not the padding now on screen;
     *   - `.rail-nav` itself scrolls, so a measurement taken once and never
     *     refreshed drifted the moment the rail's own scroll position moved
     *     it independently of any navigation.
     *
     * None of that is a bug in *this* component's logic — `rowFor` still
     * finds the right element every time. It is a bug in re-measuring only
     * on navigation when the row's on-screen position can also change for
     * reasons that are not a navigation. A DOM measurement kept in sync with
     * layout needs a `ResizeObserver` and a scroll listener on top of the
     * route effect, which is a lot of moving parts to keep a 3px bar in
     * place next to a background colour that was already correct.
     *
     * So the bar is gone, and `.nav-link.active::before` (components.css)
     * draws it instead: pure CSS, positioned by the row's own box, updated by
     * the browser's normal layout pass for free on every one of the cases
     * above. There is nothing left to measure and nothing left to go stale.
     * `.nav-link.active`'s background is unchanged — the design intent this
     * replaces (the active row is obviously active on its own, flourish or
     * not) did not depend on the flourish being JS in the first place.
     */
</script>

<aside class="rail">
  <div class="rail-head">
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

    <!-- The one action in this product that creates knowledge rather than
         reading it, and until 0.10.0 it read as the fourteenth item in a list
         of places. A rail is a list of *where you are*; this is a *do*, so it
         does not live in the list.

         Author mode only: a reader in buyer mode has no screens behind it and
         a primary action that opens a page they cannot use is worse than no
         action. -->
    {#if mode === "author"}
        <a class="rail-action" href={href("packs")}>
            <span class="rail-action-plus" aria-hidden="true">+</span>
            Start a new pack
        </a>
    {/if}
  </div>

    <nav class="rail-nav">
        {#each groups as group, index (group.title)}
            <div class="nav-slot" style="--slot: {index}">
                <NavGroup {group} {current} {href} figures={reading} />
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
