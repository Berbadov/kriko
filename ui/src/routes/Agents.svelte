<script lang="ts">
    import Connect from "./Connect.svelte";

    /* The agent side of this app.
     *
     * This used to be two lenses — Connect, and a Console that drove the same
     * API by hand when a harness could not. The console ran no shell; it was
     * a safe, API-only prompt on purpose. That stopped being enough the day a
     * harness itself needed a one-time interactive `login` — no API call can
     * do that on the CLI's behalf. An embedded terminal took its place and has
     * since been removed (§2.9); the shell that survives is `kriko tui`'s
     * pass-through, which is where an interactive `login` belongs anyway: a
     * one-time setup step is an operator's job, not a screen the reader keeps.
     *
     * Wiring is the one thing left, so it is the only thing rendered.
     *
     * This screen also used to render the whole of `Planes.prefs.svelte`
     * above `Connect`, which put a search provider, an LLM catalogue and two
     * cost tables above the page's own heading — every one of them a
     * decision about the paid plane, on the screen about agents. The reader
     * called the result "all separate" and was describing exactly that.
     * `Connect` now renders `Agents.prefs.svelte` itself, in the one place
     * it belongs: directly under the list of agents it is about. The rest
     * stayed in Settings, where the other spending choices are.
     */
</script>

<Connect />
