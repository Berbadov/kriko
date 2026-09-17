<script lang="ts">
    import Connect from "./Connect.svelte";
    import PlanePrefs from "../lib/Planes.prefs.svelte";

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
     */
</script>

<!-- Which agent, before how it is wired.
     "No preferred agent thingy" was a fair reading of this screen: the choice
     existed, in Settings, which is not where anyone goes to think about
     agents. A preference about agents belongs on the agents screen; it is the
     same panel rendered in both places rather than two that can disagree. -->
<PlanePrefs />

<Connect />
