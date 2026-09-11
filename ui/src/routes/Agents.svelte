<script lang="ts">
    import Connect from "./Connect.svelte";

    /* The agent side of this app.
     *
     * This used to be two lenses — Connect, and a Console that drove the same
     * API by hand when a harness could not. The console ran no shell; it was
     * a safe, API-only prompt on purpose. That stopped being enough the day a
     * harness itself needed a one-time interactive `login` — no API call can
     * do that on the CLI's behalf — so the console is gone and a real
     * terminal (`lib/shell/TerminalPanel.svelte`) took its place: always
     * reachable from the rail, not tucked behind a lens here, because a
     * shell is not a research feature the way Connect is.
     *
     * Wiring is the one thing left, so it is the only thing rendered.
     */
</script>

<Connect />
