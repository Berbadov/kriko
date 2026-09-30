<script lang="ts">
    import Jobs from "./Jobs.svelte";
    import Operations from "./Operations.svelte";
    import ResearchRuns from "../lib/ResearchRuns.svelte";
    import Usage from "../lib/Usage.svelte";
    import Pipeline from "./Pipeline.svelte";
    import Submissions from "./Submissions.svelte";
    import { setQuery } from "../lib/router";

    /* One screen for "what has this installation been doing".
     *
     * Runs, Knowledge pipeline and What researchers sent were three rail
     * entries, and that was the Subjects/Coverage/Health mistake again: not
     * three places, one question asked at three depths. A run says whether
     * long work is *going* and what it printed. The pipeline says what it
     * *did* — sources read, findings kept, refusals and why; a run that
     * gathered nothing and a run that lost everything at the grounding check
     * look identical in a job log. Submissions say what arrived through the
     * agent door and what the gate made of it. Anyone chasing "did that
     * research actually land" needed all three and had to hold the answer in
     * their head across two navigations.
     *
     * This is a shell, deliberately. The three screens are rendered
     * unchanged, each keeping its own heading, its own fetching and its own
     * tests — merging their *code* would be a rewrite of three working
     * screens to fix a navigation problem. What was wrong was the rail.
     *
     * No `<h2>` of its own for the same reason: the child's heading is the
     * page title and it changes with the lens, which is more use than the
     * word "Activity" sitting above it twice.
     */

    type Lens = "live" | "runs" | "pipeline" | "submissions";
    const LENSES: { id: Lens; label: string }[] = [
        // First, and the default: the other three answer "what happened",
        // which is only the interesting question once something has. This one
        // answers "what is happening", including the operations this app did
        // not start — an agent working through the MCP server was invisible
        // here entirely (B122).
        { id: "live", label: "Live" },
        { id: "runs", label: "Runs" },
        { id: "pipeline", label: "Pipeline" },
        { id: "submissions", label: "Submissions" },
    ];

    // The lens arrives from the route: `#/jobs` is the address a job-starting
    // POST's own response points at, and `#/submissions` is in this app's
    // hints. A bookmark must land on the lens it named (see nav.ts ALIASES).
    let { lens: initial = "live" }: { lens?: string } = $props();
    const asLens = (named: string): Lens =>
        (LENSES.some((l) => l.id === named) ? named : "live") as Lens;
    let lens = $state<Lens>("live" as Lens);
    $effect.pre(() => {
        lens = asLens(initial);
    });

    // A tab click used to change only local state (shell-9, ops-9): reload,
    // Back and a pasted link all disagreed with what was on screen. Writing
    // it into the query makes the lens shareable and reload-stable the same
    // way Knowledge's lens is; `replaceState` (setQuery), not a navigation —
    // switching lenses is not leaving Activity, so it must not push a Back
    // entry per tab click.
    function choose(id: Lens) {
        lens = id;
        setQuery("lens", id);
    }

    // WAI-ARIA tabs: only the selected tab is in the Tab order, and
    // Left/Right/Home/End move both focus and the selection (ops-21).
    function onTabKey(event: KeyboardEvent, index: number) {
        const move = (to: number) => {
            const next = LENSES[(to + LENSES.length) % LENSES.length];
            choose(next.id);
            document.getElementById(`activity-tab-${next.id}`)?.focus();
        };
        if (event.key === "ArrowRight") move(index + 1);
        else if (event.key === "ArrowLeft") move(index - 1);
        else if (event.key === "Home") move(0);
        else if (event.key === "End") move(LENSES.length - 1);
        else return;
        event.preventDefault();
    }
</script>

<div class="lenses" role="tablist" aria-label="Activity">
    {#each LENSES as candidate, index (candidate.id)}
        <button
            id="activity-tab-{candidate.id}"
            class="tab"
            role="tab"
            aria-selected={lens === candidate.id}
            aria-controls="activity-panel"
            tabindex={lens === candidate.id ? 0 : -1}
            class:active={lens === candidate.id}
            onclick={() => choose(candidate.id)}
            onkeydown={(event) => onTabKey(event, index)}>{candidate.label}</button
        >
    {/each}
</div>

<!-- Keyed, so switching lens mounts the screen rather than reusing a
     same-shaped one. Each of these three fetches on init; a swap in place
     would show the previous lens's rows under the new lens's heading for as
     long as the request takes. -->
<div role="tabpanel" id="activity-panel" aria-label="Activity">
{#key lens}
    {#if lens === "live"}
        <Operations />
    {:else if lens === "runs"}
        <Jobs />
        <!-- Under the jobs, not a lens of its own: a run and the job that ran
             it are two views of one thing, and a reader chasing "did that
             research land, and can I undo it" needed both. -->
        <ResearchRuns />
        <!-- And the sums, last: the reader arrives here for a run and leaves
             with the only question a list of runs cannot answer. -->
        <Usage />
    {:else if lens === "pipeline"}
        <Pipeline />
    {:else}
        <Submissions />
    {/if}
{/key}
</div>
