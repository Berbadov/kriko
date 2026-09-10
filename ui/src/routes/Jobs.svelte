<script lang="ts">
    import { api } from "../lib/api";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { follow, isLive, stateWord } from "../lib/jobs";
    import type { Job } from "../lib/types";

    let jobs = $state<Job[]>([]);
    // The exception, not a rendering of it: Failure reads the status to
    // decide what the reader can do next, and String(cause) has already
    // thrown that away (B72).
    let error = $state<unknown>(null);
    let open = $state<string | null>(null);
    let root = $state("");
    let busy = $state(false);

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
        try {
            await api.cancelJob(job.job_id);
            replace(await api.job(job.job_id));
        } catch (cause) {
            error = cause;
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
            const { job_id } = await api.retryJob(job.job_id);
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
    its result, so a restart or a closed tab loses nothing.
</p>

<details class="authoring">
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
                bind:value={category}
                placeholder="cordless drills, espresso machines, e-bikes"
            />
        </label>
        <button type="submit" disabled={busy || !category.trim()}>
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
                <button onclick={() => cancel(job)}>Cancel</button>
            {:else}
                <button onclick={() => retry(job)}>Run again</button>
            {/if}
        </p>
        {#if open === job.job_id}
            <pre class="log">{job.log || "nothing logged yet"}</pre>
            {#if job.result}
                <pre class="log">{JSON.stringify(job.result, null, 2)}</pre>
            {/if}
        {/if}
    </article>
{/each}
