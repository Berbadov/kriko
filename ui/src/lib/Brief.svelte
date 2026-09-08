<script lang="ts">
    import { api } from "./api";
    import Failure from "./Failure.svelte";
    import { follow, stateWord } from "./jobs";
    import { hashWith } from "./router";
    import type { Job } from "./types";

    /* The half of Research that was computed and thrown away.
     *
     * The $0 plane's `gather` returns nothing by design — a coding agent whose
     * subscription is already paid for does the reading — so the job's real
     * and only product is the **brief**: what to look for, in the pack's own
     * terms, and what counts as evidence. Until this component existed the
     * Coverage page rendered the job's one-word message and nothing else, so
     * pressing Research looked exactly like pressing a dead button: the job
     * ran, succeeded, wrote seven queries and a full brief, and the reader was
     * shown the word "done".
     *
     * So the contract here is: never report a state without reporting the
     * artifact. If the job produced a brief, the brief is on screen, copyable,
     * next to the one sentence that says who is supposed to act on it.
     */
    let {
        subjectId,
        packId,
        label,
        onClose,
    }: {
        subjectId: string;
        packId: string;
        label: string;
        onClose?: () => void;
    } = $props();

    let job = $state<Job | null>(null);
    let error = $state<unknown>(null);
    let copied = $state("");

    // Result fields, read defensively: the job's result is a plain dict from
    // the handler and a version skew must degrade to "no brief yet", never to
    // a component that throws while rendering a success.
    const result = $derived((job?.result ?? {}) as Record<string, unknown>);
    const brief = $derived(typeof result.brief === "string" ? result.brief : "");
    const queries = $derived(
        Array.isArray(result.queries) ? (result.queries as string[]) : [],
    );
    const documents = $derived(
        typeof result.documents === "number" ? result.documents : null,
    );
    const plane = $derived(typeof result.plane === "string" ? result.plane : "");
    const kept = $derived(Array.isArray(result.accepted) ? result.accepted.length : 0);
    const refused = $derived(Array.isArray(result.rejected) ? result.rejected.length : 0);

    async function start() {
        error = "";
        job = null;
        try {
            const { job_id } = await api.research({
                subject_id: subjectId,
                pack_id: packId,
            });
            job = await api.job(job_id);
            follow(job_id, (update) => (job = update));
        } catch (cause) {
            // Inline, never thrown: one subject failing to start research must
            // not take the screen it was opened from down with it.
            error = cause;
        }
    }
    void start();

    async function copy(what: string, text: string) {
        try {
            await navigator.clipboard.writeText(text);
            copied = what;
        } catch {
            copied = ""; // a denied clipboard is not an error worth a banner
        }
    }
</script>

<article class="card brief enter" aria-label="Research brief for {label}">
    <header class="brief-head">
        <div>
            <h3>Research · {label}</h3>
            <span class="meta">
                {#if job && !job.done}
                    <span class="live-dot"></span>
                {/if}
                {job ? stateWord(job) : "starting…"}{job?.message ? ` — ${job.message}` : ""}
            </span>
        </div>
        {#if onClose}
            <button class="ghost" onclick={onClose} aria-label="Close the brief">Close</button>
        {/if}
    </header>

    {#if error}
        <Failure {error} />
    {/if}

    {#if brief}
        <!-- Said before the brief, not after. The reader's question at this
             moment is "so did it find anything?", and the honest answer is
             "nothing was searched — that is what the brief is for". Burying
             that under a scroll is how the button came to look broken. -->
        <p class="meta">
            Kriko searched nothing.
            {#if documents === 0}
                The <code>{plane || "agent"}</code> plane costs $0 precisely because it
                does not: a coding agent you already pay for does the reading.
            {/if}
            Hand this brief to a connected agent — it can submit findings back through
            the same checked acceptance path — or paste it into any agent session
            yourself.
        </p>
        <div class="brief-do">
            <button onclick={() => copy("brief", brief)}>
                {copied === "brief" ? "Copied" : "Copy the brief"}
            </button>
            <a class="tab" href={hashWith({}, "connect")}>Connect an agent</a>
            {#if queries.length}
                <button class="ghost" onclick={() => copy("queries", queries.join("\n"))}>
                    {copied === "queries" ? "Copied" : `Copy ${queries.length} queries`}
                </button>
            {/if}
        </div>

        {#if kept || refused}
            <p class="state {kept ? 'ok' : 'empty'}">
                {kept} claim(s) kept, {refused} refused.
            </p>
        {/if}

        {#if queries.length}
            <details>
                <summary>What it would search for ({queries.length})</summary>
                <ul class="queries">
                    {#each queries as query (query)}
                        <li><code>{query}</code></li>
                    {/each}
                </ul>
            </details>
        {/if}

        <pre class="brief-body">{brief}</pre>
    {:else if job && job.done}
        <p class="state empty">
            This run produced no brief. Its log is below, and the Runs screen keeps it.
        </p>
    {:else}
        <p class="skeleton" style="height: 6rem">Planning the research…</p>
    {/if}

    {#if job?.log}
        <details>
            <summary>Run log</summary>
            <pre class="log">{job.log}</pre>
        </details>
    {/if}
</article>

<style>
    .brief-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--s-3);
    }
    .brief-head h3 {
        margin: 0;
    }
    .brief-head .meta {
        display: block;
    }
    .brief-do {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--s-2);
        margin: var(--s-3) 0;
    }
    .queries {
        margin: 0;
        padding-left: var(--s-5);
    }
    /* Bounded, because a brief is a page of prose and the screen it opens on
     * is a list the reader still needs to be able to get back to. */
    .brief-body,
    .log {
        max-height: 22rem;
        overflow: auto;
        white-space: pre-wrap;
        line-height: var(--lh-read);
    }
</style>
