<script lang="ts">
    import { api } from "../lib/api";
    import { follow, isLive, stateWord } from "../lib/jobs";
    import type { Job } from "../lib/types";

    let jobs = $state<Job[]>([]);
    let error = $state("");
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
            error = String(cause);
        }
    };

    $effect(() => {
        void load();
        return () => {
            stops.forEach((stop) => stop());
            stops.clear();
        };
    });

    async function build() {
        if (!root.trim()) return;
        busy = true;
        error = "";
        try {
            const { job_id } = await api.buildPack(root.trim());
            const job = await api.job(job_id);
            replace(job);
            watch(job);
            open = job_id;
        } catch (cause) {
            error = String(cause);
        } finally {
            busy = false;
        }
    }

    async function cancel(job: Job) {
        try {
            await api.cancelJob(job.job_id);
            replace(await api.job(job.job_id));
        } catch (cause) {
            error = String(cause);
        }
    }

    const percent = (job: Job) => Math.round((job.progress ?? 0) * 100);
    const subjectOf = (job: Job) =>
        String(job.params?.subject_id ?? job.params?.root ?? "");
</script>

<h2>Jobs</h2>
<p class="lede">
    Research and pack builds run here, not in a terminal. A job keeps its log and
    its result, so a restart or a closed tab loses nothing.
</p>

<form class="ask" onsubmit={(event) => (event.preventDefault(), build())}>
    <label class="field grow">
        <span>Build a pack from a directory</span>
        <input bind:value={root} placeholder="packs/drill" />
    </label>
    <button type="submit" disabled={busy || !root.trim()}>Build and install</button>
</form>

{#if error}
    <p class="state error">{error}</p>
{/if}

{#if !jobs.length}
    <p class="state empty">
        No jobs yet. Start one here, or from a gap on the Coverage screen.
    </p>
{/if}

{#each jobs as job (job.job_id)}
    <article class="card job" class:live={isLive(job)}>
        <h3>
            {job.kind === "research" ? "Research" : "Build"}
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
