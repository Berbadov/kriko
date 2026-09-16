<script lang="ts">
    import Connect from "./Connect.svelte";
    import PlanePrefs from "../lib/Planes.prefs.svelte";

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

<!-- Which agent, before how it is wired.
     "No preferred agent thingy" was a fair reading of this screen: the choice
     existed, in Settings, which is not where anyone goes to think about
     agents. A preference about agents belongs on the agents screen; it is the
     same panel rendered in both places rather than two that can disagree. -->
<PlanePrefs />

<Connect />
