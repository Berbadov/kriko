<script lang="ts">
    /* Every glyph this app draws, in one table.
     *
     * This started as `shell/NavIcon.svelte` — one icon per destination in
     * the rail — and the reasoning there holds everywhere, so the table
     * moved here rather than being copied: the app has to work with no
     * network (that is the premise), the static bundle is served by FastAPI
     * so every extra file is another path to get wrong, and an icon font
     * renders as a box on first paint, which on a rail is the one element
     * the reader uses to find their way around.
     *
     * `NavIcon` is a thin wrapper over this now, so the rail keeps its
     * `.nav-icon` class and the one CSS rule that styles it.
     *
     * Every `<h2>` and `<h3>` on a screen carries one (B159), drawn by the
     * heading rule in `styles/components.css`; `lib/headings.test.ts` holds
     * the screens to it, so a heading added later without a symbol fails the
     * suite rather than shipping bare.
     *
     * Stroke-based on `currentColor`, so whatever colours the surrounding
     * text colours the glyph and hover/active states need no second rule.
     * `aria-hidden` throughout: every icon here sits beside a word that
     * already says the same thing, and a screen reader announcing
     * "agent, agent" is worse than silence.
     *
     * An unknown name renders an empty box of the same size rather than a
     * placeholder mark. A screen added without a glyph should look
     * unfinished to us and ordinary to the reader.
     *
     * A closed vocabulary of this app's own screens and concepts — no pack
     * ever names one of these, which is why the table may live in the
     * frontend at all (`test_ui_contains_no_pack_vocabulary`).
     */
    let {
        name,
        size = 18,
        class: klass = "icon",
    }: { name: string; size?: number; class?: string } = $props();

    const PATHS: Record<string, string[]> = {
        // --- destinations in the rail ---
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
        // a funnel with drops below it: sources in, claims out
        pipeline: ["M4 5h16l-6 7v6l-4 2v-8z", "M17.5 17.5v.01", "M20.5 20.5v.01"],
        // an inbox tray: what came in through the door
        submissions: ["M3.5 13.5 6 5h12l2.5 8.5v5h-17z", "M3.5 13.5h4l1.5 2.5h6l1.5-2.5h4"],
        // a pulse trace: what this installation has been doing
        activity: ["M3 12h4l2.5-6 4 12 2.5-6h5"],
        // two nodes joined, with the second doubled: an agent on the other
        // end, and the console you drive it from
        agents: [
            "M6.5 9a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0",
            "M14 15a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0",
            "M11 10.5 14.5 13.5",
            "M4 19h5",
        ],
        // a prompt caret
        console: ["M3.5 5h17v14h-17z", "M7 10l2.5 2L7 14", "M12.5 14.5h4"],
        // two nodes joined: an agent on the other end
        connect: ["M6.5 9a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0", "M14 15a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0", "M11 10.5 14.5 13.5"],
        // sliders, not a cog: these are preferences, not machinery
        settings: ["M4 8h9", "M17 8h3", "M4 16h4", "M12 16h8", "M15 8a2 2 0 1 0-4 0a2 2 0 1 0 4 0", "M10 16a2 2 0 1 0-4 0a2 2 0 1 0 4 0"],
        // an i in a ring
        about: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M12 11v6", "M12 8v.01"],
        // a globe with a horizon: the sites out there this install can read
        sites: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M3.5 10h17", "M3.5 14.5h17", "M12 3c2.5 2.4 3.8 5.4 3.8 9s-1.3 6.6-3.8 9", "M12 3C9.5 5.4 8.2 8.4 8.2 12s1.3 6.6 3.8 9"],
        // a ruler with a measured span under it: the benchmark measures, it
        // does not run — a stopwatch would promise the wrong thing
        bench: ["M3 6h18v5H3z", "M7 6v2.5", "M11 6v3.5", "M15 6v2.5", "M19 6v3.5", "M4 15.5h16", "M4 14v3", "M20 14v3"],
        // a lifebuoy-ish first-run marker
        welcome: ["M12 3 14.4 9.1 21 9.6l-5 4.2 1.6 6.4L12 16.8 6.4 20.2 8 13.8l-5-4.2 6.6-.5z"],

        // --- the Agents screen, which is what this table left the rail for ---
        // a terminal window: one agent, the thing Kriko actually starts
        agent: ["M3.5 4.5h17v15h-17z", "M7 9.5 9.5 12 7 14.5", "M12.5 14.5h4.5"],
        // a chip: the LLM inside whichever agent is driving
        llm: [
            "M8 8h8v8H8z",
            "M6 6h12v12H6z",
            "M10 3v3", "M14 3v3", "M10 18v3", "M14 18v3",
            "M3 10h3", "M3 14h3", "M18 10h3", "M18 14h3",
        ],
        // a dial with its needle part-way round: how hard it thinks
        effort: ["M4 17a8 8 0 1 1 16 0", "M12 17l4-5.5", "M12 17v.01"],
        // a magnifier: which engine reads the web
        search: ["M5 11a6 6 0 1 0 12 0a6 6 0 1 0-12 0", "M15.5 15.5 20 20"],
        // a coin with a slice cut: what it has cost
        cost: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M14.5 9.2a3 3 0 1 0 0 5.6", "M12 6.5v11"],
        // an arrow landing in a page: the agent read something
        fetch: ["M5 3h9l5 5v13H5z", "M14 3v5h5", "M12 11v5", "M9.5 13.5 12 16l2.5-2.5"],
        // a checklist: the rows an agenda works down
        agenda: ["M5 3.5h14v17H5z", "M8.5 8.5 10 10l2.5-2.5", "M8.5 15 10 16.5l2.5-2.5", "M14 9h3", "M14 15.5h3"],
        // a plug: writing this app's address into a harness's config
        plug: ["M9 3v5", "M15 3v5", "M6.5 8h11v3a5.5 5.5 0 0 1-11 0z", "M12 16.5V21"],
        // a book: the brief the agent is handed
        skill: ["M4 4.5h6a2.5 2.5 0 0 1 2 2.5v13a2 2 0 0 0-2-1.5H4z", "M20 4.5h-6a2.5 2.5 0 0 0-2 2.5v13a2 2 0 0 1 2-1.5h6z"],
        // a calendar: which plane runs unattended
        schedule: ["M4 6h16v14H4z", "M4 10h16", "M8.5 3.5V6", "M15.5 3.5V6", "M8 14h3"],
        // a tick in a ring: it answered
        ok: ["M12 3a9 9 0 1 0 9 9a9 9 0 1 0-9-9", "M8 12.3 11 15.2 16.2 9"],
        // a warning triangle
        warn: ["M12 4 21 19.5H3z", "M12 10v4", "M12 17v.01"],
        // a download arrow: something to go and install
        download: ["M12 4v10", "M8.5 11 12 14.5 15.5 11", "M4.5 18.5h15"],

        // --- section symbols (B159) ---
        // Headings and rail group titles carry one, and none is a letter: a
        // letter in a heading reads as part of the word. These are drawn for
        // the section, not for a destination, so a heading and the row that
        // opens it can differ.
        // a shield with a tick: the group about using what is known
        verify: ["M12 3 5 6v5.5c0 4.2 2.8 7.4 7 9.5 4.2-2.1 7-5.3 7-9.5V6z", "M8.8 12l2.4 2.4 4.2-4.6"],
        // three sheets: knowledge as a stack
        layers: ["M12 3.5 3.5 8 12 12.5 20.5 8z", "M3.5 12 12 16.5 20.5 12", "M3.5 16 12 20.5 20.5 16"],
        // two slabs with a light each: the machinery
        server: ["M4 4.5h16v6H4z", "M4 13.5h16v6H4z", "M7.5 7.5v.01", "M7.5 16.5v.01"],
        // a screen on a stand: this installation
        monitor: ["M3.5 4.5h17v11h-17z", "M9 20h6", "M12 15.5V20"],
        // a key: what unlocks a provider
        key: ["M5 14a4 4 0 1 0 8 0a4 4 0 1 0-8 0", "M12 11.5 20 4", "M17 7l2.5 2.5", "M14.5 9.5 16.5 11.5"],
        // a pencil: describe it by hand
        edit: ["M4 20l1-4 11-11 3 3-11 11z", "M14 7l3 3"],
        // a plus: start something new
        plus: ["M12 5v14", "M5 12h14"],
        // a circling arrow: do it again
        refresh: ["M20 12a8 8 0 1 1-2.5-5.8", "M20 4v5h-5"],
        // a label: the marks a source carries
        tag: ["M3.5 12.5V4.5h8l9 9-8 8z", "M8 8.5v.01"],
        // three bars: a measured spread
        chart: ["M4 20h16", "M6 20v-6", "M11 20V6", "M16 20v-9"],
        // an eye: what is shown
        eye: ["M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z", "M9.5 12a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0"],
        // a drum: what is stored
        database: [
            "M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3z",
            "M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6",
            "M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6",
        ],
        // a chevron: a folded group (rotated by CSS when it is open)
        chevron: ["M9 6l6 6-6 6"],
        // four cells: a grid of choices
        grid: ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"],
    };

    const paths = $derived(PATHS[name] ?? []);
</script>

{#if paths.length}
    <svg
        class={klass}
        viewBox="0 0 24 24"
        width={size}
        height={size}
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
    <!-- Reserve the same box, so a glyph-less row does not shift its label
         out of the column every other row lines up in. -->
    <span class={klass} style="width:{size}px;height:{size}px" aria-hidden="true"></span>
{/if}
