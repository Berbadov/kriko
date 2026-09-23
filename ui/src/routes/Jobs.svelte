<script lang="ts">
    import { tick } from "svelte";
    import { route, setQuery } from "../lib/router";
    import { api } from "../lib/api";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { canCancel, follow, isLive, stateWord } from "../lib/jobs";
    import type { Job } from "../lib/types";

    let jobs = $state<Job[]>([]);
    // The exception, not a rendering of it: Failure reads the status to
    // decide what the reader can do next, and String(cause) has already
    // thrown that away (B72).
    let error = $state<unknown>(null);
    let open = $state<string | null>(null);
    let root = $state("");
    let busy = $state(false);
    let cancelPending = $state<string[]>([]);
    /* What the reader has typed back, per job and then per question id.
     *
     * Kept here rather than on the row because the row is replaced wholesale
     * every time the stream ticks — a draft held on `job` would be erased
     * twice a second by the thing that is supposed to be showing it. */
    let answers = $state<Record<string, Record<string, string>>>({});

    // One follower per live job, kept in a map so a re-render does not open a
    // second stream for the same row.
    const stops = new Map<string, () => void>();

    const replace = (job: Job) => {
        const index = jobs.findIndex((candidate) => candidate.job_id === job.job_id);
        if (index === -1) jobs = [job, ...jobs];
        else jobs[index] = job;
        if (job.done) {
            stops.get(job.job_id)?.();
            stops.delete(job.job_id);
        }
    };

    const watch = (job: Job) => {
        if (!isLive(job) || stops.has(job.job_id)) return;
        stops.set(job.job_id, follow(job.job_id, replace));
    };

    const load = async () => {
        try {
            jobs = (await api.jobs()).items ?? [];
            jobs.forEach(watch);
        } catch (cause) {
            error = cause;
        }
    };

    $effect(() => {
        void load();
        return () => {
            stops.forEach((stop) => stop());
            stops.clear();
        };
    });

    // ── starting a pack: one field, and an agent does the rest ──────────
    //
    // What was here asked for a directory, an id, a name and an identity
    // table before it would write anything, and the reader's verdict on that
    // was "it's gotta be automated with agents". They were right, and not
    // only about the typing: three of those four are decisions somebody who
    // has read the category can take well and somebody who has not cannot
    // take at all. The identity table is the sharp one — too few keys and
    // unrelated rows collide into one subject, too many and one thing splits
    // across subjects that never see each other's claims, and neither failure
    // raises anything. Asking for it first was asking for the one answer the
    // reader was least equipped to give.
    //
    // So: a category in plain words, one press. The agent proposes the data,
    // the engine writes the files, and the reader installs from Knowledge —
    // three steps and three different authorities, which is why nothing here
    // reaches the store.
    let category = $state("");
    let authoring: HTMLDetailsElement;
    let categoryInput: HTMLInputElement;

    $effect(() => {
        if ($route.query.author !== "new") return;
        authoring.open = true;
        let active = true;
        void tick().then(() => {
            if (!active) return;
            categoryInput.focus();
            setQuery("author", undefined);
        });
        return () => { active = false; };
    });

    async function authorPack() {
        if (!category.trim()) return;
        busy = true;
        error = null;
        try {
            const { job_id } = await api.authorPack(category.trim());
            const job = await api.job(job_id);
            replace(job);
            watch(job);
            // Opened straight away, because this run is worth watching: it is
            // several minutes of an agent reading, and the log is where the
            // reader sees that it is reading rather than hung.
            open = job_id;
        } catch (cause) {
            error = cause;
        } finally {
            busy = false;
        }
    }

    async function build() {
        if (!root.trim()) return;
        busy = true;
        error = null;
        try {
            const { job_id } = await api.buildPack(root.trim());
            const job = await api.job(job_id);
            replace(job);
            watch(job);
            open = job_id;
        } catch (cause) {
            error = cause;
        } finally {
            busy = false;
        }
    }

    async function cancel(job: Job) {
        if (!canCancel(job) || cancelPending.includes(job.job_id)) return;
        cancelPending = [...cancelPending, job.job_id];
        try {
            await api.cancelJob(job.job_id);
            replace(await api.job(job.job_id));
        } catch (cause) {
            error = cause;
        } finally {
            cancelPending = cancelPending.filter((id) => id !== job.job_id);
        }
    }

    /* Saying something to a run that is still going.
     *
     * The questions below this are the *structured* path: the run stopped,
     * wrote a question with options, and the form re-applies the answer to a
     * fresh attempt. This is the unstructured one, and it is what B120 left
     * open — a harness run streams its thinking out and took nothing in, so a
     * run that paused on something the pack's own question schema never
     * anticipated could be watched and stopped and nothing else.
     *
     * Per job id, because two runs may be live at once and a draft typed
     * against one must not appear under the other. */
    let saying = $state<Record<string, string>>({});
    let sayPending = $state<Record<string, boolean>>({});
    let sayNote = $state<Record<string, string>>({});

    async function say(job: Job) {
        const text = (saying[job.job_id] || "").trim();
        if (!text || sayPending[job.job_id]) return;
        sayPending = { ...sayPending, [job.job_id]: true };
        try {
            const answer = await api.sayToJob(job.job_id, text);
            // Cleared only on delivery. A run that ended mid-sentence should
            // leave the reader holding what they wrote, not silently eat it.
            if (answer.delivered) {
                saying = { ...saying, [job.job_id]: "" };
                sayNote = { ...sayNote, [job.job_id]: "Sent." };
            } else {
                sayNote = {
                    ...sayNote,
                    [job.job_id]: "This run had already finished. Nothing was sent.",
                };
            }
        } catch (cause) {
            error = cause;
        } finally {
            sayPending = { ...sayPending, [job.job_id]: false };
        }
    }

    /** Run a finished job's work again.
     *
     * A failure here is usually a network that was down or a source that was
     * slow — nothing about the request was wrong, and retyping it from the
     * form was the only way back. The new row keeps `retry_of`, so the two
     * attempts stay legible as two attempts rather than one confusing
     * duplicate, and the failed row keeps its log: the reason it failed is the
     * most useful thing on this screen and a retry must not overwrite it.
     */
    async function retry(job: Job) {
        try {
            const { job_id } = await api.retryJob(job.job_id, answers[job.job_id] ?? {});
            delete answers[job.job_id];
            const fresh = await api.job(job_id);
            replace(fresh);
            watch(fresh);
            open = job_id;
        } catch (cause) {
            error = cause;
        }
    }

    const percent = (job: Job) => Math.round((job.progress ?? 0) * 100);
    const subjectOf = (job: Job) =>
        String(job.params?.subject_id ?? job.params?.category ?? job.params?.root ?? "");

    /** What kind of work a row was, in the reader's words.
     *
     * A map rather than a ternary because there are now three kinds and the
     * third one — an agent writing a whole pack — read as "Build", which is
     * the one thing it deliberately does not do.
     */
    const KINDS: Record<string, string> = {
        research: "Research",
        agenda_run: "Research",
        research_undo: "Undo",
        pack_author: "New pack",
        pack_build: "Build",
        pack_update: "Update",
    };
    const kindWord = (job: Job) => KINDS[job.kind] ?? job.kind;
</script>

<!-- "Runs", which is what the rail has always called it. The heading said
     "Jobs" — an implementation word for the row in `app.sqlite` — and now that
     this is a lens under Activity the mismatch is visible in one glance
     instead of across a navigation. -->
<h2>Runs</h2>
<p class="lede">
    Research and pack builds run here, not in a terminal. A job keeps its log and
    saved results. Cancellation stops at a safe checkpoint; an in-flight request
    may finish. Only checkpointed results survive a restart.
</p>

<details class="authoring" bind:this={authoring}>
    <summary>Start a new pack</summary>
    <p class="meta">
        Name a category in a few words and your own coding agent writes the whole
        pack — what tells two of these apart, the bar a claim has to clear, what
        to search for, and a first honest row. It lands as a draft you can read
        on Knowledge; nothing is installed until you press Install there.
    </p>
    <form
        class="ask"
        onsubmit={(event) => (event.preventDefault(), authorPack())}
    >
        <label class="field grow">
            <span>What is the category?</span>
            <input
                bind:this={categoryInput}
                bind:value={category}
                placeholder="cordless drills, espresso machines, e-bikes"
            />
        </label>
        <button class="primary" type="submit" disabled={busy || !category.trim()}>
            Have my agent write it
        </button>
    </form>
    <p class="meta">
        Needs a coding-agent command-line tool installed — the same one the
        Research plane uses, and it costs nothing beyond the subscription you
        already pay for. Without one, connect your agent under Agents and let it
        use <code>draft_pack</code> instead.
    </p>
</details>

<form class="ask" onsubmit={(event) => (event.preventDefault(), build())}>
    <label class="field grow">
        <span>Build a pack from a directory</span>
        <input bind:value={root} placeholder="packs/drill" />
    </label>
    <button type="submit" disabled={busy || !root.trim()}>Build and install</button>
</form>

{#if error}
    <Failure {error} retry={load} />
{/if}

{#if !jobs.length}
    <EmptyState
        title="No runs yet"
        detail="Long work is a row here rather than a request that hangs — research
                and pack builds both land on this screen, and their log outlives
                the page. Start one above, or from a gap on Coverage."
        actionLabel="Find a gap"
        actionHref="#/coverage"
    />
{/if}

{#each jobs as job (job.job_id)}
    <article class="card job" class:live={isLive(job)}>
        <h3>
            {kindWord(job)}
            <span class="meta">{subjectOf(job)}</span>
            <span class="badge state-{job.state}">
                <!-- Only on a job that is still moving. A badge that reads
                     "running" on a page nobody has refreshed says the same
                     thing as one that is stale; the dot is what separates
                     them without the reader having to reload to find out. -->
                {#if isLive(job)}<span class="live-dot"></span>{/if}
                {stateWord(job)}
            </span>
        </h3>
        {#if isLive(job)}
            <div class="bar" role="progressbar" aria-valuenow={percent(job)}>
                <span style="width: {percent(job)}%"></span>
            </div>
        {/if}
        <p class="meta">{job.message || "…"}</p>
        <p class="row">
            <button
                onclick={() => (open = open === job.job_id ? null : job.job_id)}
                aria-expanded={open === job.job_id}>Log</button
            >
            {#if isLive(job)}
                <button
                    disabled={!canCancel(job) || cancelPending.includes(job.job_id)}
                    onclick={() => cancel(job)}
                >{job.state === "cancelling" || cancelPending.includes(job.job_id) ? "Stopping…" : "Cancel"}</button>
            {:else}
                <button onclick={() => retry(job)}>Run again</button>
            {/if}
        </p>
        {#if isLive(job)}
            <!-- Offered on every live run rather than only when one has
                 asked something, because nothing tells us it asked: the
                 question is a sentence in the agent's own output, not a
                 field. A box that appears only when we are sure is a box
                 that is never there when it is needed. -->
            <form class="say" onsubmit={(event) => { event.preventDefault(); say(job); }}>
                <!-- Written out rather than `bind:`, for the same reason the
                     question form below is: the backing record starts empty,
                     and a binding onto a slot that does not exist yet is
                     cleared again by the next poll — which lands every second
                     on exactly the runs this box is offered on. -->
                <input
                    aria-label="Reply to this run"
                    placeholder="Answer this run…"
                    value={saying[job.job_id] ?? ""}
                    oninput={(event) => {
                        saying = { ...saying, [job.job_id]: event.currentTarget.value };
                    }}
                    disabled={sayPending[job.job_id]}
                />
                <button type="submit" disabled={sayPending[job.job_id] || !(saying[job.job_id] || "").trim()}
                    >{sayPending[job.job_id] ? "Sending…" : "Send"}</button
                >
            </form>
            {#if sayNote[job.job_id]}
                <p class="meta" aria-live="polite">{sayNote[job.job_id]}</p>
            {/if}
        {/if}
        {#if job.attention?.questions?.length}
            <!-- The answer form, and the reason this screen changed shape.
                 The questions were only ever written into the run log, so a
                 mechanism that already knew how to ask, normalise and re-apply
                 an answer reached the reader as a paragraph of prose with
                 nothing to type into. Rendering them as controls is the whole
                 of the fix on this side.

                 Not a modal, and it blocks nothing: the run already finished
                 on its own assumptions. Answering changes the *next* run,
                 which is why the submit is the retry rather than a "send". -->
            <form
                class="asked"
                onsubmit={(event) => { event.preventDefault(); retry(job); }}
            >
                <p class="meta">{job.attention.say}</p>
                {#each job.attention.questions as question (question.id)}
                    <div class="field">
                        <label for="{job.job_id}-{question.id}">{question.ask}</label>
                        {#if question.options.length}
                            <select
                                id="{job.job_id}-{question.id}"
                                value={answers[job.job_id]?.[question.id] ?? ""}
                                onchange={(event) => {
                                    answers[job.job_id] ??= {};
                                    answers[job.job_id][question.id] = event.currentTarget.value;
                                }}
                            >
                                <!-- The assumption is the first option and the
                                     selected one, so leaving the form alone
                                     re-runs exactly what already ran. -->
                                <option value="">It assumed {question.default}</option>
                                {#each question.options as option (option)}
                                    <option value={option}>{option}</option>
                                {/each}
                            </select>
                        {:else}
                            <input
                                id="{job.job_id}-{question.id}"
                                placeholder="It assumed {question.default}"
                                value={answers[job.job_id]?.[question.id] ?? ""}
                                oninput={(event) => {
                                    answers[job.job_id] ??= {};
                                    answers[job.job_id][question.id] = event.currentTarget.value;
                                }}
                            />
                        {/if}
                        {#if question.because}
                            <p class="meta">{question.because}</p>
                        {/if}
                    </div>
                {/each}
                <p class="row">
                    <button class="primary" type="submit">Answer and run again</button>
                </p>
            </form>
        {/if}
        {#if open === job.job_id}
            <pre class="log">{job.log || "nothing logged yet"}</pre>
            {#if job.result}
                <pre class="log">{JSON.stringify(job.result, null, 2)}</pre>
            {/if}
        {/if}
    </article>
{/each}
