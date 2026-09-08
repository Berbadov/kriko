<script lang="ts">
    /* What the knowledge pipeline is doing, while it does it.
     *
     * The Runs screen answers "is it still going, and what did it print".
     * That is a job's question. This screen answers the pipeline's: how many
     * sources were read, how many findings the grounding check kept, which
     * source each one came from, and which of the four stages a run is
     * standing in. Those distinguish "found nothing" from "found plenty and
     * lost it all at acceptance" — two situations that look identical in a
     * job log and are entirely different problems.
     *
     * The stage names come from the server, not from a list here. The stage
     * vocabulary belongs to the pipeline; a second copy in TypeScript is a
     * second place to forget when a stage is added.
     */
    import { api } from "../lib/api";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { followPipeline, runProgress, runWord, stageCount } from "../lib/pipeline";
    import type { PipelineFrame, PipelineRun } from "../lib/types";

    let frame = $state<PipelineFrame | null>(null);
    let runs = $state<PipelineRun[]>([]);
    let error = $state<unknown>(null);
    let picked = $state<string | undefined>(undefined);
    let ready = $state(false);

    const load = async () => {
        try {
            runs = (await api.pipelineRuns()).runs ?? [];
        } catch (cause) {
            error = cause;
        } finally {
            ready = true;
        }
    };

    $effect(() => {
        void load();
    });

    // One follower, torn down and rebuilt when the reader picks a different
    // run. Tracked on `picked` alone: re-subscribing on every frame would
    // reopen the stream against itself forever.
    $effect(() => {
        const target = picked;
        const stop = followPipeline((next) => {
            // Events accumulate. The server sends only what is new since the
            // cursor it was given, so appending is not an optimisation — a
            // replace would show the last 300 lines of a long run and drop
            // everything the reader watched arrive.
            const before = frame && frame.run.run_id === next.run.run_id ? frame.events : [];
            frame = { ...next, events: [...before, ...next.events] };
            if (!next.live) void load();
        }, target);
        return stop;
    });

    const progress = $derived(frame ? runProgress(frame.stages) : 0);
    const tokens = $derived(
        !frame
            ? ""
            : frame.run.tokens_counted
              ? `${frame.run.tokens?.toLocaleString()} tokens`
              : // Not "0". The agent plane's marginal cost really is zero and
                // the API plane's is really measured; a run where nobody
                // counted must not render as free.
                "not metered on this plane",
    );

    const shortTime = (at: string | null) =>
        at ? new Date(at).toLocaleTimeString() : "";

    const host = (url: string) => {
        try {
            return new URL(url).hostname.replace(/^www\./, "");
        } catch {
            return url;
        }
    };
</script>

<h2>Knowledge pipeline</h2>
<p class="meta">
    Four stages turn sources into claims: Discovery finds candidates,
    Extraction pulls grounded findings out of them, Ingestion puts those
    through the acceptance check, and Ledgering writes down what was kept and
    what was refused. The refusals are the point — a run that kept nothing is
    the one worth reading.
</p>

{#if error}
    <Failure {error} />
{/if}

{#if frame}
    {@const run = frame.run}
    <section class="run enter">
        <header class="run-head">
            <div>
                <h3>
                    {run.subject || run.subject_id || "a run with no subject"}
                    {#if run.state === "running"}
                        <span class="live-dot" aria-hidden="true"></span>
                    {/if}
                </h3>
                <p class="meta">
                    {runWord(run.state)} · {run.plane || "unknown"} plane · started {shortTime(
                        run.started_at,
                    )}
                    {#if run.pack_id}· {run.pack_id}{/if}
                </p>
            </div>
            <dl class="totals">
                <div><dt>Sources</dt><dd>{run.sources}</dd></div>
                <div><dt>Findings</dt><dd>{run.findings}</dd></div>
                <div><dt>Kept</dt><dd class="kept">{run.accepted}</dd></div>
                <div><dt>Refused</dt><dd class="refused">{run.refused}</dd></div>
            </dl>
        </header>

        <!-- Counted in settled stages rather than interpolated from item
             counts: nothing knows how many findings a source will yield, so a
             percentage derived from them moves backwards. -->
        <div
            class="bar"
            role="progressbar"
            aria-valuenow={Math.round(progress * 100)}
            aria-valuemin="0"
            aria-valuemax="100"
            aria-label="pipeline progress"
        >
            <span class="fill" style="--at: {progress}"></span>
        </div>

        {#if run.error}
            <p class="state error">{run.error}</p>
        {/if}

        <ol class="stages">
            {#each frame.stages as stage, index (stage.stage)}
                <li
                    class="stage {stage.state}"
                    style="--slot: {index}"
                    aria-current={stage.state === "running" ? "step" : undefined}
                >
                    <span class="stage-top">
                        <strong>{stage.label}</strong>
                        {#if stage.state === "running"}
                            <span class="live-dot" aria-hidden="true"></span>
                        {/if}
                    </span>
                    <span class="stage-state">{stage.state}</span>
                    {#if stageCount(stage, run)}
                        <span class="stage-count">{stageCount(stage, run)}</span>
                    {/if}
                    {#if stage.detail}
                        <span class="stage-detail">{stage.detail}</span>
                    {/if}
                </li>
            {/each}
        </ol>

        <p class="meta metered">{tokens}</p>

        <h4>What happened</h4>
        {#if frame.events.length}
            <!-- Its own scroll container, not the page's. A live log that
                 lengthens the document pushes the stage rail off the top of
                 the screen exactly when the reader is watching it.
                 `role="log"` and a tab stop, because a region that scrolls
                 and cannot be focused is a region a keyboard cannot read —
                 and this one is where the refusals are. -->
            <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
            <div class="feed" role="log" tabindex="0" aria-label="pipeline events">
            <ol class="lines">
                {#each frame.events as event (event.event_id)}
                    <li class="line {event.level}">
                        <span class="stamp">{shortTime(event.at)}</span>
                        <span class="where">{event.stage}</span>
                        <span class="what">{event.message}</span>
                        {#if event.source_url}
                            <a
                                class="src"
                                href={event.source_url}
                                target="_blank"
                                rel="noreferrer">{host(event.source_url)}</a
                            >
                        {/if}
                    </li>
                {/each}
            </ol>
            </div>
        {:else}
            <p class="state empty">Nothing recorded for this run yet.</p>
        {/if}
    </section>
{:else if ready && !runs.length}
    <EmptyState
        title="The pipeline has not run yet"
        detail="Research a subject and this screen fills in as it goes — stage by stage, source by source."
        actionLabel="Go to Runs"
        actionHref="#/jobs"
    />
{:else if !ready}
    <p class="state loading">Loading…</p>
{/if}

{#if runs.length}
    <h3>Earlier runs</h3>
    <table>
        <thead>
            <tr>
                <th>Subject</th><th>Plane</th><th>State</th><th>Sources</th>
                <th>Kept</th><th>Refused</th><th>Started</th>
            </tr>
        </thead>
        <tbody>
            {#each runs as run (run.run_id)}
                <tr class:picked={frame?.run.run_id === run.run_id}>
                    <td>
                        <!-- A button, not a click handler on the row. A row
                             that only responds to a mouse is a row a keyboard
                             cannot reach, and this is the control that
                             chooses what the whole screen above is showing. -->
                        <button
                            class="link pick"
                            aria-pressed={frame?.run.run_id === run.run_id}
                            onclick={() => (picked = run.run_id)}
                            >{run.subject || run.subject_id || "—"}</button
                        >
                    </td>
                    <td>{run.plane || "—"}</td>
                    <td>{runWord(run.state)}</td>
                    <td>{run.sources}</td>
                    <td>{run.accepted}</td>
                    <td>{run.refused}</td>
                    <td>{shortTime(run.started_at)}</td>
                </tr>
            {/each}
        </tbody>
    </table>
    <p class="meta">
        Pick a run to read it. Runs are kept for a while and then
        dropped whole — events and stages with them, because half an event log
        is more misleading than none.
    </p>
{/if}

<style>
    /* Every value here is a token. The colour rule is enforced on the
     * stylesheets in src/styles/; it holds in a component for the same
     * reason — a literal is the wrong value in one of the three themes. */
    .run {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        margin-bottom: var(--s-5);
    }

    .run-head {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--s-3);
    }

    .run-head h3 {
        margin: 0;
    }

    .totals {
        display: flex;
        gap: var(--s-4);
        margin: 0;
    }

    .totals div {
        display: flex;
        flex-direction: column;
    }

    .totals dt {
        font-size: var(--t-xs);
        color: var(--dim);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .totals dd {
        margin: 0;
        font-size: var(--t-lg);
        font-variant-numeric: tabular-nums;
    }

    .totals dd.kept {
        color: var(--accent);
    }

    .totals dd.refused {
        color: var(--high);
    }

    .bar {
        height: 4px;
        border-radius: var(--radius-sm);
        background: var(--panel-2);
        overflow: hidden;
    }

    .fill {
        display: block;
        height: 100%;
        width: calc(var(--at) * 100%);
        background: var(--accent);
        transition: width var(--dur-slow) var(--ease-out);
    }

    /* The pipeline's shape, present from the first frame. Four boxes that
     * appear one at a time read as a UI loading; four that fill in read as a
     * pipeline making progress — which is why the server sends `waiting`
     * stages rather than omitting them. */
    .stages {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
        gap: var(--s-2);
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .stage {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: var(--s-2);
        border: 1px solid var(--line);
        border-radius: var(--radius-sm);
        background: var(--panel);
        /* Staggered by position, so the rail reads left to right on arrival
         * — the direction the pipeline actually runs. */
        animation: kriko-enter var(--dur-slow) var(--ease-out) both;
        animation-delay: calc(var(--slot) * var(--stagger));
        transition:
            border-color var(--dur-fast) var(--ease),
            background-color var(--dur-fast) var(--ease);
    }

    .stage-top {
        display: flex;
        align-items: center;
        gap: var(--s-1);
    }

    .stage-state {
        font-size: var(--t-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--dim);
    }

    .stage-count {
        font-size: var(--t-sm);
        font-variant-numeric: tabular-nums;
    }

    .stage-detail {
        font-size: var(--t-xs);
        color: var(--dim);
        line-height: var(--lh-sm);
    }

    .stage.waiting {
        opacity: 0.55;
    }

    .stage.running {
        border-color: var(--accent);
        background: var(--accent-soft);
    }

    .stage.done {
        border-color: var(--accent-lo);
    }

    /* Skipped is not failed, and must not look like it. A stage that
     * correctly did nothing — the $0 plane fetches no sources — reads as
     * quiet, not as a problem. */
    .stage.skipped {
        border-style: dashed;
        color: var(--dim);
    }

    .stage.failed {
        border-color: var(--high);
        background: var(--high-soft);
    }

    .metered {
        margin: 0;
    }

    .feed {
        max-height: 22rem;
        overflow-y: auto;
        border: 1px solid var(--line);
        border-radius: var(--radius-sm);
        background: var(--panel);
        font-family: var(--font-mono);
        font-size: var(--t-sm);
    }

    .lines {
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .line {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2);
        padding: 4px var(--s-2);
        border-bottom: 1px solid var(--line);
        animation: kriko-enter var(--dur-fast) var(--ease-out) both;
    }

    .line:last-child {
        border-bottom: none;
    }

    .stamp,
    .where {
        color: var(--dim);
        font-variant-numeric: tabular-nums;
    }

    .what {
        flex: 1 1 20ch;
        /* A long refusal reason wraps rather than widening the container:
         * a monospace log that scrolls sideways is a log nobody reads. */
        min-width: 0;
        overflow-wrap: anywhere;
    }

    .line.kept .what {
        color: var(--accent-hi);
    }

    .line.refused .what {
        color: var(--high);
    }

    .line.warn .what {
        color: var(--medium);
    }

    tr.picked {
        background: var(--accent-soft);
    }

    .pick {
        text-align: left;
    }

    @media (prefers-reduced-motion: reduce) {
        /* Landed, not frozen — the final frame of each rule above. */
        .stage,
        .line {
            animation: none;
        }
        .fill {
            transition: none;
        }
    }
</style>
