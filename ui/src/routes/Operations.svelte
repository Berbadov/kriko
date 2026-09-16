<script lang="ts">
    import { onDestroy, onMount } from "svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { doorWord, followOperations, stateWord, took } from "../lib/operations";
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
            stop = followOperations(page.last_id, add);
            live = true;
        } catch (cause) {
            // The exception itself, not a sentence squeezed out of it:
            // `Failure.svelte` derives the remedy, and a view that flattens it
            // here has thrown away the status the remedy is built from (B79).
            failed = cause;
        }
    });

    onDestroy(() => stop?.());

    const summary = (row: Operation): string => {
        const text = row.state === "failed" ? row.error : row.response_json;
        return text.length > 200 ? text.slice(0, 200) + "…" : text;
    };

    const clock = (at: string) => (at || "").slice(11, 19) || (at || "").slice(0, 10);
</script>

<h2>Live</h2>
<p class="lede">
    Every operation this installation runs, as it happens — a tool call from your
    own agent, a job you started here, an analysis the extension asked for. It is
    a feed, not a record: what a run <em>produced</em> is under Runs and What
    researchers sent, and outlives this.
</p>

{#if failed}
    <Failure error={failed} />
{/if}

<p class="meta" aria-live="polite">
    {#if live}Watching.{:else}Not watching.{/if}
    {rows.filter((one) => one.state === "running").length} running now.
</p>

{#if !rows.length}
    <EmptyState
        title="Nothing has happened yet"
        detail="Connect your coding agent to Kriko and ask it to research something, or
                start a research job here. Both land in this feed — the door each came
                in by is shown on the row."
        actionLabel="Connect an agent"
        actionHref="#/connect"
    />
{:else}
    <ul class="klist" aria-label="Operations">
        {#each rows as row (row.op_id)}
            <li class="krow" class:running={row.state === "running"}>
                <div class="kmain">
                    <span class="klabel">{row.name}</span>
                    <span class="meta">
                        {doorWord(row.door)} · {row.kind}
                        {#if row.subject_id}· {row.subject_id}{/if}
                    </span>
                    {#if open === row.op_id}
                        <pre class="detail">{row.request_json}</pre>
                        {#if summary(row)}<pre class="detail">{summary(row)}</pre>{/if}
                    {/if}
                </div>
                <span class="meta">
                    {clock(row.started_at)}
                    {#if row.state !== "ok"}<span
                            class="badge"
                            class:error={row.state === "failed"}>{stateWord(row.state)}</span
                        >{/if}
                    {#if row.ms}· {took(row.ms)}{/if}
                </span>
                <button
                    class="link"
                    aria-expanded={open === row.op_id}
                    onclick={() => (open = open === row.op_id ? null : row.op_id)}
                    >Details</button
                >
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
</style>
