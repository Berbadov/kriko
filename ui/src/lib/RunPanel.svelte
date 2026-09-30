<script lang="ts">
    import { tick } from "svelte";
    import Icon from "./Icon.svelte";
    import ProviderMark from "./ProviderMark.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import { canCancel, isLive, kindWord, stateWord } from "./jobs";
    import { doing, tally } from "./live";
    import { elapsed } from "./time";
    import type { Job } from "./types";

    /* One running agent, as it works (B176).
     *
     * The dark panel under the Run form. It shows who is running, what it is
     * doing this second, and each source and finding as the event arrives,
     * without a Log button to press. The events are the server's own
     * classification of the job's log (`app/web/livefeed.py`), which the
     * stream pushes within a fraction of a second of the CLI printing; this
     * component only draws them.
     *
     * The reader can stop the run and can answer it from here: a reply box for
     * anything, and a press for a question the run put with options. Both go
     * over the routes Activity already uses, so nothing about a run depends on
     * which screen it is watched from.
     */
    let {
        job,
        agent,
        now = Date.now(),
    }: { job: Job; agent: { id: string; label: string }; now?: number } = $props();

    const live = $derived(isLive(job));
    const feed = $derived(job.feed ?? []);
    const counts = $derived(tally(feed));
    const questions = $derived(live ? (job.attention?.questions ?? []) : []);

    let stopping = $state(false);
    let failure = $state("");
    let reply = $state("");
    let sending = $state(false);
    let sent = $state("");
    let scroller = $state<HTMLDivElement>();

    // New events land at the bottom, so the newest is always in view. Scrolled
    // after the DOM has the row, or the last one sits just below the fold.
    $effect(() => {
        void feed.length;
        void tick().then(() => {
            if (scroller) scroller.scrollTop = scroller.scrollHeight;
        });
    });

    async function stop() {
        if (!canCancel(job) || stopping) return;
        stopping = true;
        failure = "";
        try {
            await api.cancelJob(job.job_id);
        } catch (cause) {
            failure = remedyFor(cause).headline;
        } finally {
            stopping = false;
        }
    }

    async function say(text: string) {
        const body = text.trim();
        if (!body || sending) return;
        sending = true;
        failure = "";
        try {
            const answer = await api.sayToJob(job.job_id, body);
            if (answer.delivered) {
                reply = "";
                sent = "Sent";
            } else {
                sent = "The run had finished";
            }
        } catch (cause) {
            failure = remedyFor(cause).headline;
        } finally {
            sending = false;
        }
    }

    const GLYPH: Record<string, string> = {
        source: "fetch",
        search: "search",
        finding: "ok",
        problem: "warn",
    };
</script>

<section class="panel" class:done={!live} aria-label="{agent.label} run">
    <header>
        <span class="who"><ProviderMark name={agent.id} size={18} /> {agent.label}</span>
        <span class="kind">{kindWord(job.kind)}</span>
        <span class="state" class:running={live}>
            {#if live}<span class="live-dot"></span>{/if}
            {stateWord(job)}
        </span>
        <span class="clock" title="Time since this run started">
            {elapsed(job.started_at ?? job.created_at, now)}
        </span>
        {#if live}
            <button
                type="button"
                class="stop"
                disabled={!canCancel(job) || stopping}
                onclick={stop}
            >
                {job.state === "cancelling" || stopping ? "Stopping" : "Stop"}
            </button>
        {/if}
    </header>

    <p class="doing" aria-live="polite">{doing(job)}</p>

    <ul class="tally" aria-label="Progress">
        <li title="Pages read"><Icon name="fetch" size={14} /> <b>{counts.sources}</b> sources</li>
        <li title="Searches run"><Icon name="search" size={14} /> <b>{counts.searches}</b> searches</li>
        <li title="Findings kept"><Icon name="ok" size={14} /> <b>{counts.findings}</b> findings</li>
        {#if counts.problems}
            <li class="bad" title="Refused or failed"><Icon name="warn" size={14} /> <b>{counts.problems}</b> problems</li>
        {/if}
    </ul>

    {#if feed.length}
        <div class="events" bind:this={scroller} role="log" aria-label="What the agent did">
            {#each feed as event, index (index + event.text)}
                <div class="event {event.kind} enter">
                    <span class="glyph" aria-hidden="true">
                        {#if GLYPH[event.kind]}<Icon name={GLYPH[event.kind]} size={13} />{:else}<span class="dot"></span>{/if}
                    </span>
                    <span class="text">{event.text}</span>
                </div>
            {/each}
        </div>
    {/if}

    {#each questions as question (question.id)}
        <fieldset class="ask">
            <legend>{question.ask}</legend>
            {#if question.options.length}
                <div class="options">
                    {#each question.options as option (option)}
                        <button
                            type="button"
                            disabled={sending}
                            onclick={() => say(`Answer to "${question.ask}": ${option}`)}
                        >
                            {option}
                        </button>
                    {/each}
                </div>
            {/if}
        </fieldset>
    {/each}

    {#if live}
        <form
            class="reply"
            onsubmit={(event) => {
                event.preventDefault();
                void say(reply);
            }}
        >
            <input
                aria-label="Reply to this run"
                placeholder="Reply to this run"
                value={reply}
                oninput={(event) => {
                    reply = event.currentTarget.value;
                    sent = "";
                }}
                disabled={sending}
            />
            <button type="submit" disabled={sending || !reply.trim()}>Send</button>
            {#if sent}<span class="sent" role="status">{sent}</span>{/if}
        </form>
    {/if}
    {#if failure}
        <p class="state error" role="alert">{failure}</p>
    {/if}
</section>

<style>
    .panel {
        background: var(--n-0);
        color: var(--n-8);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: var(--s-3);
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .panel.done {
        opacity: 0.85;
    }
    header {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        flex-wrap: wrap;
    }
    .who {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        color: var(--n-9);
        font-weight: 600;
    }
    .kind,
    .clock {
        color: var(--dim);
        font-size: var(--t-xs);
    }
    .state {
        display: inline-flex;
        align-items: center;
        gap: var(--s-1);
        font-size: var(--t-xs);
        color: var(--dim);
    }
    .state.running {
        color: var(--low);
    }
    .stop {
        margin-inline-start: auto;
    }
    .doing {
        margin: 0;
        color: var(--n-9);
        overflow-wrap: anywhere;
    }
    .tally {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-1) var(--s-4);
        list-style: none;
        margin: 0;
        padding: 0;
        color: var(--dim);
        font-size: var(--t-xs);
    }
    .tally li {
        display: inline-flex;
        align-items: center;
        gap: var(--s-1);
    }
    .tally b {
        color: var(--n-9);
        font-variant-numeric: tabular-nums;
    }
    .tally .bad,
    .tally .bad b {
        color: var(--high);
    }
    .events {
        max-height: 16rem;
        overflow: auto;
        border-top: 1px solid var(--line-soft);
        padding-block-start: var(--s-2);
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
        font-size: var(--t-xs);
        line-height: var(--lh-xs);
    }
    .event {
        display: flex;
        gap: var(--s-2);
        align-items: baseline;
        color: var(--n-7);
    }
    .event .glyph {
        flex: none;
        display: inline-flex;
        align-self: center;
    }
    .event .dot {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background: var(--n-5);
    }
    .event .text {
        overflow-wrap: anywhere;
    }
    .event.source {
        color: var(--n-8);
    }
    .event.finding {
        color: var(--low);
    }
    .event.problem {
        color: var(--high);
    }
    .ask {
        border: 1px solid var(--line);
        border-radius: var(--radius-sm);
        padding: var(--s-2);
    }
    .options {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2);
    }
    .reply {
        display: flex;
        gap: var(--s-2);
        align-items: center;
    }
    .reply input {
        flex: 1;
        min-width: 0;
    }
    .sent {
        color: var(--dim);
        font-size: var(--t-xs);
    }
</style>
