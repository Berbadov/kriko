<script lang="ts">
    import { api } from "./api";
    import Failure from "./Failure.svelte";
    import Pick from "./Pick.svelte";
    import Scale from "./Scale.svelte";
    import { follow, stateWord } from "./jobs";
    import { hashWith } from "./router";
    import type { Job, ResearchPlane } from "./types";

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
    let harness = $state("");
    let llm = $state("");
    /* How much reading this run is worth. Empty means the server's default,
     * which is what every run did before the dial reached this screen — the
     * brief itself is free and instant either way, so nothing here waits on
     * `/api/scales` answering. */
    let scale = $state("");
    let maxDocuments = $state(0);
    /* Which planes this machine can run, so the button that starts one is only
     * offered when it would work. Best-effort: a planes call that fails costs
     * the reader the button and never the brief. */
    let planes = $state<ResearchPlane[]>([]);
    const harnessPlane = $derived(planes.find((p) => p.id === "harness"));

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

    async function start(backend = "agent") {
        error = "";
        job = null;
        try {
            const { job_id } = await api.research({
                subject_id: subjectId,
                pack_id: packId,
                backend,
                ...(harness ? { harness } : {}),
                ...(backend === "harness" && llm ? { llm } : {}),
                // Only on a run that actually reads. The `agent` plane
                // gathers nothing by design, so a depth sent with it would
                // be a number with no effect — which is how a control comes
                // to look broken.
                ...(backend === "harness" && scale ? { scale } : {}),
                ...(backend === "harness" && maxDocuments
                    ? { max_documents: maxDocuments }
                    : {}),
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
    // After the brief, never before it: the brief is instant and free, and a
    // reader looking at this screen wants it on the page rather than after a
    // second request that only decides which buttons to draw.
    api.researchPlanes()
        // `?? []` because a payload without the field is a payload from an
        // older engine, and a derived that reads `.find` off undefined takes
        // the whole card down with it.
        .then((data) => (planes = data.planes ?? []))
        .catch(() => (planes = []));

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
        {#if documents === 0}
            <p class="meta">
                Kriko searched nothing on the <code>{plane || "agent"}</code> plane —
                that is what makes it cost $0: an agent you already pay for does the
                reading. Either let Kriko start that agent for you with the button
                below, or hand it the brief yourself. Both end at the same checked
                acceptance path.
            </p>
        {:else}
            <p class="meta">
                Read {documents} source(s) on the <code>{plane}</code> plane. Every
                finding went through the same grounding check as one an agent
                submits by hand, and the whole run can be taken back out from
                <strong>Activity → Runs</strong>.
            </p>
        {/if}
        <div class="brief-do">
            <!-- The one button that closes the loop without the reader
                 leaving the app. Offered only when a CLI was actually found:
                 a button whose failure message is "install something" is a
                 worse answer than the sentence under the disabled card. -->
            {#if harnessPlane?.ready}
                {@const chosenHarness = (harnessPlane.harnesses ?? []).find(
                    (one) => one.id === (harness || harnessPlane.selected_harness))}
                <label>Agent
                    <select bind:value={harness} disabled={!!job && !job.done}>
                        <option value="">Use preference ({harnessPlane.selected_harness || 'automatic'})</option>
                        {#each harnessPlane.harnesses ?? [] as one (one.id)}
                            <option value={one.id}>{one.label}</option>
                        {/each}
                    </select>
                </label>
                {#if chosenHarness?.llm_selectable}
                    <label>LLM
                        <Pick
                            bind:value={llm}
                            disabled={!!job && !job.done}
                            options={(chosenHarness.llms ?? []).map((name) => ({ value: name }))}
                            emptyLabel={chosenHarness.llm
                                ? `Preference (${chosenHarness.llm})`
                                : "CLI default"}
                            hint={chosenHarness.llm_hint}
                        />
                    </label>
                {/if}
                <Scale
                    bind:scale
                    bind:maxDocuments
                    disabled={!!job && !job.done}
                    label="How much to read"
                />
                {#if harnessPlane.reason}<p class="meta">{harnessPlane.reason}</p>{/if}
                <button
                    disabled={!!job && !job.done}
                    onclick={() => start("harness")}
                >
                    {job && !job.done ? "Running…" : "Run my agent on this"}
                </button>
            {/if}
            <button class="ghost" onclick={() => copy("brief", brief)}>
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
