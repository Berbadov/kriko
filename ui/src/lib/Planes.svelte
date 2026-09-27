<script lang="ts">
    import Async from "./Async.svelte";
    import Icon from "./Icon.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import { follow, stateWord } from "./jobs";
    import Pick from "./Pick.svelte";
    import Scale from "./Scale.svelte";
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
    let llm = $state("");
    let harness = $state("");
    let search = $state("");
    const selection = () => ({ llm, harness, search });
    const refresh = () => (promise = api.researchPlanes(selection()));
    /* Effort is the agent's saved preference (the key Agents writes), not a
     * per-run field — so it is saved and the planes re-read, which is what
     * makes this select and the one on Agents always agree. */
    async function pickEffort(id: string, level: string) {
        try {
            await api.savePrefs({ [`harness_effort_${id.replace(/-/g, "_")}`]: level });
        } catch (cause) {
            failed = remedyFor(cause).headline;
        }
        refresh();
    }
    let rows = $state(5);
    let budget = $state(0.2);
    /* How deep each of those rows goes. The agenda is the screen that most
     * needs this: whatever one subject costs, this multiplies it by `rows`,
     * so the difference between Quick and Deep here is the difference
     * between a run and an afternoon. */
    let scale = $state("");
    let maxDocuments = $state(0);
    let job = $state<Job | null>(null);
    let failed = $state("");
    let stop: (() => void) | undefined;

    async function run(plane: ResearchPlane) {
        failed = "";
        job = null;
        try {
            const started = await api.runAgenda({
                rows,
                ...selection(),
                backend: plane.id,
                // Every plane that reads honours the depth. The `agent`
                // plane gathers nothing by design, so it is the one where a
                // number would have no effect — the server ignores it there
                // either way, and sending it would only imply otherwise.
                ...(plane.id === "agent" ? {} : { scale, ...(maxDocuments ? { max_documents: maxDocuments } : {}) }),
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

    /* A glyph per plane, on the same closed set of ids `NAMES` is keyed off:
     * a terminal for the CLI Kriko starts, a book for the brief you carry to
     * your own agent, a chip for the one that spends tokens. An id with no
     * glyph draws an empty box of the same size rather than shifting the
     * title out of line. */
    const GLYPHS: Record<string, string> = {
        harness: "agent",
        agent: "skill",
        api: "llm",
    };
</script>

<article class="card">
    <h3><Icon name="knowledge" /> Build knowledge</h3>
    <p class="meta">
        Three planes, the same claims at the end of all of them: whatever either one finds
        goes through the same grounding check and the same acceptance path, tagged
        with which plane found it, and any run can be taken back out from
        <strong>Activity → Runs</strong>.
    </p>

    <Async {promise} loading="Reading…" retry={refresh}>
        {#snippet children(data: { planes: ResearchPlane[]; default?: string })}
            {@const harnessPlane = data.planes.find((plane) => plane.id === "harness")}
            {@const harnessChoices = harnessPlane?.harnesses ?? []}
            {@const activeHarness =
                harnessChoices.find((one) => one.id === (harness || harnessPlane?.selected_harness))}
            <!-- B146: this was a collapsed "This run's choices", which is where
                 "I can't see the effort limit" came from. Open, in one row. -->
            <div class="choices" role="group" aria-label="This run's choices">
                <label>
                    Agent
                    <select bind:value={harness} onchange={refresh}>
                        <option value="">Use preference</option>
                        {#each harnessChoices as one (one.id)}
                            <option value={one.id}>{one.label}</option>
                        {/each}
                    </select>
                </label>
                <label>
                    LLM
                    <Pick
                        bind:value={llm}
                        onpick={refresh}
                        disabled={!!activeHarness && !activeHarness.llm_selectable}
                        options={(activeHarness?.llms ?? []).map((name) => ({ value: name }))}
                        emptyLabel={activeHarness
                            ? activeHarness.llm_selectable
                                ? activeHarness.llm
                                    ? `Preference (${activeHarness.llm})`
                                    : "CLI default"
                                : "no LLM switch on this agent"
                            : "Use preference"}
                        hint={activeHarness?.llm_hint ?? ""}
                    />
                </label>
                <label>
                    Search
                    <select bind:value={search} onchange={refresh}>
                        <option value="">Use preference</option>
                        <option value="exa">Exa</option>
                        <option value="tavily">Tavily</option>
                    </select>
                </label>
                {#if activeHarness && (activeHarness.efforts ?? []).length}
                    <label>
                        Effort
                        <select
                            value={activeHarness.effort ?? ""}
                            onchange={(event) =>
                                pickEffort(activeHarness.id, event.currentTarget.value)}
                        >
                            <option value="">CLI default</option>
                            {#each activeHarness.efforts ?? [] as level (level)}
                                <option value={level}>{level}</option>
                            {/each}
                        </select>
                    </label>
                {/if}
            </div>
            <p class="meta">
                Empty uses your preferences. Agent, LLM and effort drive "Run my agent";
                LLM and search drive "Kriko itself". Lower effort is faster and cheaper.
            </p>
            <div class="planes">
                {#each data.planes as plane (plane.id)}
                    <section class="plane" class:inert={!plane.ready}>
                        <div class="plane-head">
                            <Icon name={GLYPHS[plane.id] ?? ""} size={19} />
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
                        {#if plane.reason}<p class="state">{plane.reason}</p>{/if}
                        {#if plane.llm}<p class="meta">Using <code>{plane.llm}</code> with {plane.search || 'no search provider'}.</p>{/if}

                        {#each (plane.harnesses ?? []).filter((one) => one.id === plane.selected_harness) as found (found.id)}
                            <p class="meta">
                                Using <strong>{found.label}</strong>
                                (<code>{found.command}</code>)
                                {#if found.llm_selectable}with <code>{found.llm || "CLI default"}</code>{/if}.
                                {#if found.needs_account}<br />Bills to {found.needs_account}.{/if}
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
                            {#if plane.id !== "agent"}
                                <Scale
                                    bind:scale
                                    bind:maxDocuments
                                    multiplier={rows}
                                    label="How much to read per subject"
                                />
                            {/if}
                            {#if plane.id === "api"}
                                <p class="meta">
                                    One ceiling for the whole run, not per subject, and a
                                    hard stop rather than a warning — the run ends the
                                    moment the next request would go past it.
                                </p>
                            {/if}
                        {:else if plane.id === "harness"}
                            <!-- The way out, not just the absence: what to
                                 install, the command that installs it, and
                                 which account it bills to — every headless
                                 run spends a subscription, quota or key the
                                 reader already holds, and "no marginal cost"
                                 is only true once they know which one. -->
                            <p class="meta">
                                No coding-agent command line found on this
                                machine. Looked for
                                <code>{(plane.looked_for ?? []).join(", ")}</code>.
                            </p>
                            {#if (plane.missing ?? []).length}
                                <ul>
                                    {#each plane.missing ?? [] as one (one.id)}
                                        <li>
                                            <strong>{one.label}</strong>
                                            {#if one.download_url}
                                                <a href={one.download_url} target="_blank" rel="noreferrer">download</a>
                                            {/if}
                                            {#if one.install_hint}<br /><code>{one.install_hint}</code>{/if}
                                            {#if one.needs_account}<br /><span class="meta">{one.needs_account}.</span>{/if}
                                        </li>
                                    {/each}
                                </ul>
                            {/if}
                            {#if plane.dirs_env}
                                <p class="meta">
                                    Already installed somewhere unusual? Point
                                    <code>{plane.dirs_env}</code> at its folder and press
                                    Verify on Agents → Connect. Searched without it:
                                    <code>{(plane.search_dirs ?? []).join(", ")}</code>.
                                </p>
                            {/if}
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
    .choices {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2) var(--s-3);
        margin-block: var(--s-3) var(--s-1);
    }
    .choices > label {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        flex: 1 1 10rem;
        max-width: 15rem;
        font-size: 0.85rem;
    }
    h3 {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }
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
