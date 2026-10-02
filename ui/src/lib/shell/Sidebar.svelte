<script lang="ts">
    import { onMount } from "svelte";
    import { hashWith, route } from "../router";
    import { figures } from "./figures";
    import { readings, watch } from "./instruments";
    import NavGroup from "./NavGroup.svelte";
    import { api } from "../api";
    import { NAV, resolve, type NavGroupSpec } from "./nav";

    /* The rail's own numbers. Started here rather than in App.svelte because
     * the rail is the only thing that reads them — a clock owned by whatever
     * happens to mount first is a clock that stops when that thing unmounts.
     * `watch` is idempotent and returns its own stop, so a remount does not
     * leave two running. */
    onMount(watch);

    /* Which foldable groups the reader closed (B167), as lower-cased titles.
     *
     * Kept in the app's settings like every other UI preference, so it survives
     * a restart; read once on mount and written on every change. A failed read
     * leaves every group open and a failed write costs the preference, never
     * the click.
     */
    const FOLDED_KEY = "rail_folded_groups";
    let folded = $state<string[]>([]);
    // A click that lands before the stored value arrives is the newer intent.
    let touched = false;
    onMount(() => {
        void api
            .settings()
            .then((all) => {
                if (touched) return;
                const stored = all?.[FOLDED_KEY];
                folded =
                    typeof stored === "string" && stored
                        ? stored.split(",").filter(Boolean)
                        : [];
            })
            .catch(() => {});
    });
    const idOf = (group: NavGroupSpec) => group.title.toLowerCase();
    /* The group the open screen is in stays open whatever was stored, so a
     * stored fold can never hide the row the reader is standing on. */
    const holdsCurrent = (group: NavGroupSpec) =>
        group.items.some((item) => item.name === current);
    const isFolded = (group: NavGroupSpec) =>
        Boolean(group.foldable) && folded.includes(idOf(group)) && !holdsCurrent(group);
    function toggle(group: NavGroupSpec) {
        const id = idOf(group);
        touched = true;
        folded = folded.includes(id) ? folded.filter((one) => one !== id) : [...folded, id];
        void api.putSettings({ [FOLDED_KEY]: folded.join(",") }).catch(() => {});
    }

    const reading = $derived(figures($readings));

    /* The rail highlights the screen that is *rendered*, which is not always
     * the screen that was asked for. `#/coverage` renders Knowledge's gaps
     * lens — App.svelte resolves that, and until this line the rail did not,
     * so arriving from the browser extension's link lit no row at all. One
     * resolve, read by every row's `.active` class, is what keeps them
     * agreeing with what is actually on screen. */
    const current = $derived(resolve($route.name).name);

    // Bare links: there is one mode (B165), so nothing rides along.
    const href = (name: string) => hashWith({}, name);

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
    <a class="brand" href={href("home")}>
        <!-- The extension's toolbar icon, the same drawing the installer's
             app icon is rendered from. The reader met this product in a
             browser toolbar; a different mark here reads as a different
             tool.

             The 64x64 drawing, not the 16x16 grid (B161: "Fix the pixelated
             Kriko logo in the top left"). The grid at 28px is a 1.75 scale, and
             no smoothing setting makes that crisp: nearest-neighbour gives
             uneven blocks and any other gives mush. The drawing is vector with
             real diagonals, and 32px is exactly half its unit, so it is drawn at
             a whole number of pixels at 100% and lands on the device grid at
             every scale a display offers above it. -->
        <!-- `/static/`, not `/`: Vite's base is /static/ because FastAPI
             mounts StaticFiles there, so a root-relative path to a
             public/ asset falls through to the SPA catch-all and the mark
             renders as a broken image. Guarded by public-assets.test.ts. -->
        <!-- The design system's wordmark (kriko-svelte/assets), white on the
             blue brand plate: the same drawing the reference rail opens with.
             The 32px mark stays in the tree for the installer's app icon. -->
        <img class="mark" src="/static/kriko-wordmark-white.svg" alt="Kriko" />
        <span class="brand-text">
            <span class="meta">local product knowledge</span>
        </span>
    </a>

  </div>

    <nav class="rail-nav">
        {#each NAV as group, index (group.title)}
            <div class="nav-slot" style="--slot: {index}">
                <NavGroup
                    {group}
                    {current}
                    {href}
                    figures={reading}
                    folded={isFolded(group)}
                    locked={Boolean(group.foldable) && holdsCurrent(group)}
                    ontoggle={() => toggle(group)}
                />
            </div>
        {/each}
    </nav>

</aside>
