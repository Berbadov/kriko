<script lang="ts">
    /* One 20px glyph per destination, inline.
     *
     * Inline and not an icon font, a sprite sheet or a CDN set, for three
     * reasons that all point the same way: the app has to work with no
     * network (it is the whole premise), the static bundle is served from
     * FastAPI so every extra file is another path to get wrong, and an icon
     * font renders as a box on first paint before it loads — on the one
     * element the reader uses to find their way around.
     *
     * Stroke-based on `currentColor` so the link's own colour drives it and
     * the active and hover states need no second rule. `aria-hidden`: the
     * label beside it already says where the link goes, and a screen reader
     * announcing "compare, compare" is worse than silence.
     *
     * Unknown names render nothing rather than a placeholder. A destination
     * added without a glyph should look unfinished to us and normal to the
     * reader, not stamped with a question mark.
     */
    let { name }: { name: string } = $props();

    // Path data, keyed by route name. A closed vocabulary of this app's own
    // screens — not pack data, which is why it may live in the frontend.
    const PATHS: Record<string, string[]> = {
        // a magnifier over a document: look something up
        check: ["M4 4h9l3 3v4", "M4 4v16h6", "M14 14.5a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0", "M19.5 19.5 22 22"],
        // a clock: what you asked before
        history: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M12 7v5l3.5 2"],
        // two columns side by side
        compare: ["M4 4h7v16H4z", "M13 4h7v16h-7z", "M4 9h7", "M13 13h7"],
        // a question mark on a sheet
        questions: ["M5 3h14v18H5z", "M9.5 8.5a2.5 2.5 0 1 1 3.7 2.2c-.8.5-1.2 1-1.2 1.9", "M12 16.5v.01"],
        // a puzzle piece: the browser half
        extension: [
            "M9 4h2a1.5 1.5 0 0 1 3 0h2a1 1 0 0 1 1 1v3a1.5 1.5 0 0 0 0 3v3a1 1 0 0 1-1 1h-3a1.5 1.5 0 0 0-3 0H7a1 1 0 0 1-1-1v-3a1.5 1.5 0 0 0 0-3V5a1 1 0 0 1 1-1z",
        ],
        // a gauge: the state of the whole store at a glance
        overview: ["M3.5 17a9 9 0 1 1 17 0", "M12 17l4.5-5"],
        // stacked shelves: browse what is known
        knowledge: ["M4 5h16", "M4 12h16", "M4 19h16", "M8 5v14"],
        // boxes: installed packs
        packs: ["M12 3 3.5 7.5 12 12l8.5-4.5z", "M3.5 7.5v9L12 21l8.5-4.5v-9", "M12 12v9"],
        // a play triangle inside a ring: work that is running
        jobs: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M10 8.5 15.5 12 10 15.5z"],
        // an inbox tray: what came in through the door
        submissions: ["M3.5 13.5 6 5h12l2.5 8.5v5h-17z", "M3.5 13.5h4l1.5 2.5h6l1.5-2.5h4"],
        // a prompt caret
        console: ["M3.5 5h17v14h-17z", "M7 10l2.5 2L7 14", "M12.5 14.5h4"],
        // two nodes joined: an agent on the other end
        connect: ["M6.5 9a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0", "M14 15a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0", "M11 10.5 14.5 13.5"],
        // sliders, not a cog: these are preferences, not machinery
        settings: ["M4 8h9", "M17 8h3", "M4 16h4", "M12 16h8", "M15 8a2 2 0 1 0-4 0a2 2 0 1 0 4 0", "M10 16a2 2 0 1 0-4 0a2 2 0 1 0 4 0"],
        // an i in a ring
        about: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M12 11v6", "M12 8v.01"],
        // a lifebuoy-ish first-run marker
        welcome: ["M12 3 14.4 9.1 21 9.6l-5 4.2 1.6 6.4L12 16.8 6.4 20.2 8 13.8l-5-4.2 6.6-.5z"],
    };

    const paths = $derived(PATHS[name] ?? []);
</script>

{#if paths.length}
    <svg
        class="nav-icon"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
        focusable="false"
    >
        {#each paths as d (d)}
            <path {d} />
        {/each}
    </svg>
{:else}
    <!-- Reserve the same box so a glyph-less destination does not shift the
         label out of the column every other link lines up in. -->
    <span class="nav-icon" aria-hidden="true"></span>
{/if}
