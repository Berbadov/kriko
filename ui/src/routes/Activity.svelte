<script lang="ts">
    import Jobs from "./Jobs.svelte";
    import Pipeline from "./Pipeline.svelte";
    import Submissions from "./Submissions.svelte";

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

    type Lens = "runs" | "pipeline" | "submissions";
    const LENSES: { id: Lens; label: string }[] = [
        { id: "runs", label: "Runs" },
        { id: "pipeline", label: "What the pipeline did" },
        { id: "submissions", label: "What researchers sent" },
    ];

    // The lens arrives from the route: `#/jobs` is the address a job-starting
    // POST's own response points at, and `#/submissions` is in this app's
    // hints. A bookmark must land on the lens it named (see nav.ts ALIASES).
    let { lens: initial = "runs" }: { lens?: string } = $props();
    let lens = $state<Lens>(
        (LENSES.some((l) => l.id === initial) ? initial : "runs") as Lens,
    );
</script>

<div class="lenses" role="tablist" aria-label="Activity">
    {#each LENSES as candidate (candidate.id)}
        <button
            class="tab"
            role="tab"
            aria-selected={lens === candidate.id}
            class:active={lens === candidate.id}
            onclick={() => (lens = candidate.id)}>{candidate.label}</button
        >
    {/each}
</div>

<!-- Keyed, so switching lens mounts the screen rather than reusing a
     same-shaped one. Each of these three fetches on init; a swap in place
     would show the previous lens's rows under the new lens's heading for as
     long as the request takes. -->
{#key lens}
    {#if lens === "runs"}
        <Jobs />
    {:else if lens === "pipeline"}
        <Pipeline />
    {:else}
        <Submissions />
    {/if}
{/key}
