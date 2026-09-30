<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import { onDestroy, onMount } from "svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { kindWord } from "../lib/jobs";
    import { clock as fmtClock } from "../lib/time";
    import {
        doorWord,
        followOperations,
        since,
        stateWord,
        stoppable,
        took,
    } from "../lib/operations";
    import type { Operation } from "../lib/types";

    /* What this installation is doing, right now, whichever door it came in.
     *
     * The gap this fills: the door the reader actually prefers is their own
     * coding agent talking to Kriko's MCP server — that is deliberate, the
     * terminal is for the person and the app is for the operations — and until
     * now that door was visible only afterwards, only as a submission, and
     * only when the operation happened to be a submission. A lookup, a brief, a
     * draft left nothing at all. So "is it doing anything?" had no answer on
     * the one screen that should have had it.
     *
     * It appends rather than re-fetches: the stream hands over rows by id, so
     * a row that arrives while the reader is reading one is added to the top
     * and nothing already on screen moves out from under them.
     */

    let rows = $state<Operation[]>([]);
    let open = $state<number | null>(null);
    let live = $state(false);
    let failed = $state<unknown>(null);
    let stop: (() => void) | undefined;

    /* A clock, so a running row can say how long it has been running.
     *
     * `ms` is written when the row closes, which means the feed knew a
     * duration for everything except the operations somebody is actually
     * watching. Ticking here rather than per row: one timer for the screen,
     * and it only runs while something is open. */
    let now = $state(Date.now());
    let ticker: ReturnType<typeof setInterval> | undefined;

    /** Which door's rows to show. `all` is not a door, it is the absence of
     *  the filter — and it is the default, because this feed's first job is
     *  to show the work the reader did not start. */
    let door = $state("all");
    /** And whether to show only what is still going. Two filters rather than
     *  one list of states: "is anything running" and "what did my agent do"
     *  are different questions and a reader asks them separately. */
    let onlyRunning = $state(false);
    /** Stop requested, by job id — the button must go quiet immediately, and
     *  a cancel is cooperative, so the row keeps running for a moment after. */
    let stopping = $state<Record<string, boolean>>({});

    /** Kept short on purpose. This is a feed, not the archive — what a run
     *  produced lives in Runs, the pipeline and Submissions, all of which
     *  outlive it. */
    const KEEP = 200;

    const add = (row: Operation) => {
        // Replace rather than prepend when the id is already here: a row is
        // written when the call starts and again when it ends, and the second
        // one is the same operation, not a new one.
        const at = rows.findIndex((one) => one.op_id === row.op_id);
        if (at >= 0) rows[at] = row;
        else rows = [row, ...rows].slice(0, KEEP);
    };

    onMount(async () => {
        try {
            const page = await api.operations(60);
            rows = page.items;
            // The ids already open when the screen loads are handed over too:
            // an operation that started before the reader opened this tab is
            // exactly the one they came here to watch, and following the
            // cursor alone would never have reported its ending.
            stop = followOperations(
                page.last_id,
                add,
                page.items.filter((one) => one.state === "running").map((one) => one.op_id),
            );
            live = true;
        } catch (cause) {
            // The exception itself, not a sentence squeezed out of it:
            // `Failure.svelte` derives the remedy, and a view that flattens it
            // here has thrown away the status the remedy is built from (B79).
            failed = cause;
        }
    });

    onDestroy(() => {
        stop?.();
        if (ticker) clearInterval(ticker);
    });

    /* The clock runs only while something is running. A feed of finished work
     * is a list, and a list does not need to be re-rendered once a second. */
    $effect(() => {
        const going = rows.some((one) => one.state === "running");
        if (going && !ticker) ticker = setInterval(() => (now = Date.now()), 1000);
        if (!going && ticker) {
            clearInterval(ticker);
            ticker = undefined;
        }
    });

    /** The doors that actually appear, in the order the feed first saw them.
     *  Derived rather than listed: a door is a string the server writes, and a
     *  hardcoded set here would quietly hide a door added later. */
    const doors = $derived([...new Set(rows.map((one) => one.door))]);

    const shown = $derived(
        rows.filter(
            (one) =>
                (door === "all" || one.door === door) &&
                (!onlyRunning || one.state === "running"),
        ),
    );

    const running = $derived(rows.filter((one) => one.state === "running").length);

    /* Stop is offered only where it is true. See `stoppable`: a job belongs to
     * the runner in this process, an MCP call belongs to the reader's own
     * agent and this installation cannot reach into it. Showing a button that
     * does nothing would be worse than showing none. */
    const cancel = async (row: Operation) => {
        const job = row.job_id;
        if (!job || stopping[job]) return;
        stopping = { ...stopping, [job]: true };
        try {
            await api.cancelJob(job);
        } catch (cause) {
            // Put the button back: the cancel did not land, and a control that
            // stays greyed out after a failure tells the reader the work is
            // stopping when it is not.
            stopping = { ...stopping, [job]: false };
            failed = cause;
        }
    };

    const summary = (row: Operation): string => {
        const text = row.state === "failed" ? row.error : row.response_json;
        return text.length > 200 ? text.slice(0, 200) + "…" : text;
    };

    const clock = (at: string) => fmtClock(at) || (at || "").slice(0, 10);

    /** The request, laid out one field per line rather than as the single
     *  compact line the server stores it in. Still the raw fields — knowing
     *  every operation's params ahead of time is exactly the kind of closed
     *  vocabulary the layering principle keeps out of this lens — but spaced
     *  out onto its own lines it reads as a form rather than as a JSON dump. */
    const detail = (json: string): string => {
        try {
            return JSON.stringify(JSON.parse(json), null, 2);
        } catch {
            return json;
        }
    };

    /** What a running row has to say for itself: the stage the job is in, and
     *  how far through. Both come off the joined `jobs` row, which is why a
     *  row that is not a job shows a running time and nothing else. */
    const elapsed = (row: Operation): string => {
        const ms = since(row, now);
        return ms === null ? "" : took(ms);
    };
</script>

<h2><Icon name="activity" size={22} /> Live</h2>
<p class="lede">
    Every operation this installation runs, as it happens: a tool call from your
    own agent, a job you started here, an analysis the extension asked for. It is
    a feed, not a record: what a run <em>produced</em> is under Runs and What
    researchers sent, and outlives this.
</p>

{#if failed}
    <Failure error={failed} />
{/if}

<p class="meta" aria-live="polite">
    {#if live}Watching.{:else}Not watching.{/if}
    {running} running now.
</p>

{#if rows.length}
    <div class="filters">
        <label>
            Door
            <select bind:value={door}>
                <option value="all">All</option>
                {#each doors as one (one)}
                    <option value={one}>{doorWord(one)}</option>
                {/each}
            </select>
        </label>
        <label class="check">
            <input type="checkbox" bind:checked={onlyRunning} />
            Running only
        </label>
    </div>
{/if}

{#if !rows.length}
    <EmptyState
        title="Nothing has happened yet"
        detail="Connect your coding agent to Kriko and ask it to research something, or
                start a research job here. Both land in this feed; the door each came
                in by is shown on the row."
        actionLabel="Connect an agent"
        actionHref="#/connect"
    />
{:else}
    {#if !shown.length}
        <p class="meta">Nothing here under this filter. {rows.length} operations in all.</p>
    {/if}
    <ul class="klist" aria-label="Operations">
        {#each shown as row (row.op_id)}
            <li class="krow" class:running={row.state === "running"}>
                <div class="kmain">
                    <span class="klabel">{row.name}</span>
                    <span class="meta">
                        {doorWord(row.door)} · {kindWord(row.kind)}
                        {#if row.subject_id}· {row.subject_id}{/if}
                    </span>
                    {#if row.state === "running" && row.note}
                        <!-- The stage, in the job's own words. This is the
                             difference between "running" and "running — it is
                             on extraction, 2 of 4": the first is a spinner. -->
                        <span class="stage" aria-live="polite">
                            {row.note}
                            {#if row.progress}· {Math.round(row.progress * 100)}%{/if}
                        </span>
                        {#if row.progress}
                            <div
                                class="bar"
                                role="progressbar"
                                aria-valuenow={Math.round(row.progress * 100)}
                                aria-valuemin="0"
                                aria-valuemax="100"
                            >
                                <span style="width: {Math.round(row.progress * 100)}%"></span>
                            </div>
                        {/if}
                    {/if}
                    {#if open === row.op_id}
                        <pre class="detail">{detail(row.request_json)}</pre>
                        {#if summary(row)}<pre class="detail">{summary(row)}</pre>{/if}
                    {/if}
                </div>
                <span class="meta">
                    {clock(row.started_at)}
                    {#if row.state !== "ok"}<span
                            class="badge"
                            class:error={row.state === "failed"}>{stateWord(row.state)}</span
                        >{/if}
                    {#if row.ms}· {took(row.ms)}
                    {:else if row.state === "running" && elapsed(row)}· {elapsed(row)}{/if}
                </span>
                <span class="acts">
                    {#if stoppable(row)}
                        <button
                            class="link"
                            disabled={stopping[row.job_id ?? ""]}
                            onclick={() => cancel(row)}
                            >{stopping[row.job_id ?? ""] ? "Stopping…" : "Stop"}</button
                        >
                    {/if}
                    <button
                        class="link"
                        aria-expanded={open === row.op_id}
                        onclick={() => (open = open === row.op_id ? null : row.op_id)}
                        >Details</button
                    >
                </span>
            </li>
        {/each}
    </ul>
{/if}

<style>
    .krow.running {
        border-left: 2px solid var(--accent);
    }
    .detail {
        margin: 0.4rem 0 0;
        padding: 0.5rem;
        background: var(--n-1, rgba(127, 127, 127, 0.08));
        border-radius: 4px;
        font-family: var(--font-mono);
        font-size: 0.78rem;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 14rem;
        overflow: auto;
    }
    .badge.error {
        color: var(--high, #f0565b);
    }
    .link {
        background: none;
        border: 0;
        color: inherit;
        opacity: 0.7;
        cursor: pointer;
        font: inherit;
        text-decoration: underline;
    }
    .link:disabled {
        cursor: default;
        opacity: 0.4;
        text-decoration: none;
    }
    .acts {
        display: flex;
        gap: 0.75rem;
        white-space: nowrap;
    }
    .filters {
        display: flex;
        gap: 1rem;
        align-items: center;
        flex-wrap: wrap;
        margin: 0 0 0.75rem;
        font-size: 0.85rem;
    }
    .filters label {
        display: flex;
        gap: 0.4rem;
        align-items: center;
        opacity: 0.85;
    }
    .filters .check {
        cursor: pointer;
    }
    .stage {
        display: block;
        margin-top: 0.2rem;
        font-size: 0.82rem;
        color: var(--accent);
    }
    .bar {
        margin-top: 0.3rem;
        height: 3px;
        border-radius: 2px;
        background: var(--n-1, rgba(127, 127, 127, 0.18));
        overflow: hidden;
        max-width: 18rem;
    }
    .bar span {
        display: block;
        height: 100%;
        background: var(--accent);
        transition: width 0.4s ease;
    }
</style>
