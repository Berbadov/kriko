<script lang="ts">
    import Async from "./Async.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import { follow, stateWord } from "./jobs";
    import type { Job, ResearchPlane } from "./types";

    /* The two ways this installation grows its own knowledge, side by side.
     *
     * The reader's own words were "I'm looking at the app itself and still
     * couldn't figure out how I'm going to build some knowledge with my
     * agents" — with every piece already built and nothing on any screen
     * saying so. Two cards is the answer: here are the two planes, here is
     * what each costs, here is which one can run right now, and here is the
     * button.
     *
     * The paid card is inert without keys rather than hidden. Hiding it would
     * answer the question with silence again; a disabled card that names its
     * prerequisite and links to it is the whole explanation in one place.
     *
     * The button runs the *agenda*, not a subject — `Agenda.svelte` above
     * shows the same rows this will work down, so what is on screen is what
     * will be researched.
     */

    let promise = $state(api.researchPlanes());
    let rows = $state(5);
    let budget = $state(0.2);
    let job = $state<Job | null>(null);
    let failed = $state("");
    let stop: (() => void) | undefined;

    async function run(plane: ResearchPlane) {
        failed = "";
        job = null;
        try {
            const started = await api.runAgenda({
                rows,
                backend: plane.id,
                // Sent only on the plane that spends. The free plane's honest
                // budget is zero, and zero means unlimited to the charger —
                // which is why the server floors it on the paid plane rather
                // than trusting whatever arrives here.
                budget_usd: plane.id === "api" ? budget : 0,
            });
            stop?.();
            stop = follow(started.job_id, (next) => (job = next));
        } catch (cause) {
            failed = remedyFor(cause).headline;
        }
    }

    const costWord = (plane: ResearchPlane) =>
        plane.cost_basis === "subscription" ? "no marginal cost" : "costs per token";

    /* Three planes now, and the names are the reader's question rather than
     * the engine's word: "who does the reading". `harness` is the one that
     * closes the loop — Kriko starts the agent itself — and it is first
     * because it is the only free plane that produces claims without the
     * reader going to a terminal. */
    const NAMES: Record<string, string> = {
        harness: "Run my agent",
        agent: "I'll run it myself",
        api: "Kriko itself",
    };
    const nameOf = (plane: ResearchPlane) => NAMES[plane.id] ?? plane.id;
</script>

<article class="card">
    <h3>Build knowledge</h3>
    <p class="meta">
        Three planes, the same claims at the end of all of them: whatever either one finds
        goes through the same grounding check and the same acceptance path, tagged
        with which plane found it, and any run can be taken back out from
        <strong>Activity → Runs</strong>.
    </p>

    <Async {promise} loading="Reading…" retry={() => (promise = api.researchPlanes())}>
        {#snippet children(data)}
            <div class="planes">
                {#each data.planes as plane (plane.id)}
                    <section class="plane" class:inert={!plane.ready}>
                        <div class="plane-head">
                            <strong>{nameOf(plane)}</strong>
                            <!-- The engine's own word, printed as well as
                                 translated: `per_token` is what the code says
                                 and a reader who greps for it should find it
                                 on the screen too. -->
                            <span class="badge" title={plane.cost_basis}>{costWord(plane)}</span>
                            <!-- Which card a button elsewhere in the app will
                                 use when nobody named a plane. The reader met
                                 the cost of not knowing this twice: the
                                 default was the plane that fetches nothing,
                                 and Research reported success having gathered
                                 nothing. Marking it is cheaper than
                                 explaining it. -->
                            {#if plane.id === data.default}
                                <span class="badge" title="what Research uses unless told otherwise"
                                    >default</span
                                >
                            {/if}
                        </div>
                        <p class="meta">{plane.what}</p>

                        {#each (plane.harnesses ?? []).slice(0, 1) as found (found.id)}
                            <p class="meta">
                                Using <strong>{found.label}</strong>
                                (<code>{found.command}</code>).
                            </p>
                        {/each}

                        <!-- Installed, found, and skipped on purpose. Left
                             unsaid, this reads as Kriko failing to notice a
                             tool the reader can see on their own PATH; said,
                             it is a sentence about what the plane requires. -->
                        {#each plane.unusable ?? [] as skipped (skipped.id)}
                            <p class="meta">
                                Not using <strong>{skipped.label}</strong>
                                (<code>{skipped.command}</code>) — {skipped.why}
                            </p>
                        {/each}

                        {#if plane.ready}
                            <form
                                class="ask"
                                onsubmit={(event) => (event.preventDefault(), run(plane))}
                            >
                                <label class="field">
                                    <span class="meta">Subjects</span>
                                    <input
                                        type="number"
                                        min="1"
                                        max="100"
                                        bind:value={rows}
                                    />
                                </label>
                                {#if plane.id === "api"}
                                    <label class="field">
                                        <span class="meta">Ceiling, $</span>
                                        <input
                                            type="number"
                                            min="0.01"
                                            max="100"
                                            step="0.01"
                                            bind:value={budget}
                                        />
                                    </label>
                                {/if}
                                <button type="submit">Research the top {rows}</button>
                            </form>
                            {#if plane.id === "api"}
                                <p class="meta">
                                    One ceiling for the whole run, not per subject, and a
                                    hard stop rather than a warning — the run ends the
                                    moment the next request would go past it.
                                </p>
                            {/if}
                        {:else if plane.id === "harness"}
                            <!-- The names, not a count: "no agent found" is
                                 only actionable if the reader can see which
                                 commands were looked for. -->
                            <p class="meta">
                                No coding-agent command line found on this
                                machine. Looked for
                                <code>{(plane.looked_for ?? []).join(", ")}</code>.
                                Install one and this card turns on.
                            </p>
                        {:else}
                            <p class="meta">
                                Needs both keys before it can run.
                                <a href="#/settings">Set them up in Settings</a>.
                            </p>
                        {/if}
                    </section>
                {/each}
            </div>
        {/snippet}
    </Async>

    {#if failed}
        <p class="state error">{failed}</p>
    {/if}
    {#if job}
        <p class="row">
            <span class="badge state-{job.state}">{stateWord(job)}</span>
            <span class="meta">{job.message || "…"}</span>
            <a href="#/jobs">Watch it</a>
        </p>
    {/if}
</article>

<style>
    .planes {
        display: grid;
        gap: var(--s-3);
        grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
        margin-block: var(--s-3);
    }
    .plane {
        padding: var(--s-3);
        border: 1px solid var(--line);
        border-radius: var(--radius);
    }
    /* Dimmed, never removed: the card that cannot run is half the answer to
       "what are my options". */
    .plane.inert {
        opacity: 0.72;
    }
    .plane-head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
</style>
