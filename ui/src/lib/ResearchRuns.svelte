<script lang="ts">
    import Async from "./Async.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import { follow } from "./jobs";
    import type { Job, ResearchRun } from "./types";

    /* Who researched what, what it cost, and the way back out.
     *
     * Under the job list rather than beside it, because a research run and the
     * job that ran it are two views of one thing and the reader arriving here
     * is asking a question the job log cannot answer: *which plane wrote these
     * claims, and can I undo it*. A job's log says what happened; this says
     * what is still in the store because of it.
     *
     * Three columns earn their place:
     *
     * * **The plane and the LLM.** "Researched automatically" is not a
     *   provenance record; a named completion API via a named search provider
     *   is one. A reader deciding whether to trust forty claims needs to know
     *   what wrote them, and which one.
     * * **What it spent.** Blank when nobody counted — the agent plane never
     *   does — which is deliberately not shown as $0.00. "Cost nothing" and
     *   "nobody measured" are different answers.
     * * **Undo.** Offered only when the server says it would do something.
     *   `undoable` comes from the run detail rather than from `claims > 0`
     *   here, so a screen can never present a button that is a no-op.
     */

    let promise = $state(api.researchRuns());
    let job = $state<Job | null>(null);
    let failed = $state("");
    let undoing = $state("");
    let stop: (() => void) | undefined;

    const refresh = () => {
        promise = api.researchRuns();
    };

    async function undo(run: ResearchRun) {
        failed = "";
        undoing = run.run_id;
        try {
            const started = await api.undoResearchRun(run.run_id);
            stop?.();
            stop = follow(started.job_id, (next) => {
                job = next;
                // Re-read once it lands: the claim counts here are the whole
                // point of the undo, and a stale zero-or-forty is the one
                // thing this screen must not show.
                if (next.done) {
                    undoing = "";
                    refresh();
                }
            });
        } catch (cause) {
            failed = remedyFor(cause).headline;
            undoing = "";
        }
    }

    const when = (run: ResearchRun) => (run.started_at || "").replace("T", " ").slice(0, 16);

    /** The plane in the reader's words, with what it used beside it. */
    function planeWord(run: ResearchRun): string {
        if (run.plane === "agent") return "your agent";
        const parts = [run.llm, run.search_provider].filter(Boolean);
        return parts.length ? `Kriko itself — ${parts.join(" via ")}` : "Kriko itself";
    }

    const OUTCOME: Record<string, string> = {
        done: "finished",
        budget: "stopped at the budget",
        cancelled: "cancelled",
        failed: "failed",
        "": "still going",
    };
</script>

<section class="runs">
    <h3>Research runs</h3>
    <p class="meta">
        Every run that wrote a claim into the store, and what it wrote. Undoing one
        removes only that run's claims — nothing another run or another door added.
    </p>

    <Async {promise} loading="Reading…" retry={refresh}>
        {#snippet children(data)}
            {#if !data.runs.length}
                <p class="state empty">
                    No research has run here yet. The two planes are on
                    <a href="#/agents">Agents → Wiring</a>.
                </p>
            {:else}
                <ul class="run-list">
                    {#each data.runs as run (run.run_id)}
                        <li class="run">
                            <div class="run-head">
                                <strong>{planeWord(run)}</strong>
                                <span class="badge">{OUTCOME[run.outcome] ?? run.outcome}</span>
                                <span class="meta">{when(run)}</span>
                            </div>
                            <p class="row">
                                <span class="meta">
                                    {run.claims} claim{run.claims === 1 ? "" : "s"} still in
                                    {#if run.removed}
                                        · {run.removed} taken back out
                                    {/if}
                                    {#if run.spent_usd !== null}
                                        · spent ${run.spent_usd.toFixed(4)}{#if run.budget_usd}
                                            of ${run.budget_usd.toFixed(2)}{/if}
                                    {/if}
                                </span>
                                {#if run.claims > 0}
                                    <button
                                        class="link-ish"
                                        disabled={undoing === run.run_id}
                                        onclick={() => undo(run)}
                                        >{undoing === run.run_id
                                            ? "Undoing…"
                                            : "Undo this run"}</button
                                    >
                                {/if}
                            </p>
                        </li>
                    {/each}
                </ul>
            {/if}
        {/snippet}
    </Async>

    {#if failed}
        <p class="state error">{failed}</p>
    {/if}
    {#if job}
        <p class="state" role="status">{job.message || "…"}</p>
    {/if}
</section>

<style>
    .runs {
        margin-block-start: var(--s-5);
    }
    .runs > .meta {
        max-width: var(--measure);
    }
    .run-list {
        list-style: none;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .run {
        padding: var(--s-3);
        border: 1px solid var(--line);
        border-radius: var(--radius);
    }
    .run-head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
</style>
