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

    // ── starting a pack, not only building one ───────────────────────────
    //
    // The app could build a directory and install the artifact, but the
    // directory itself had to be created by hand from a document — so
    // authoring a category, the thing this whole platform is for, was the one
    // task with no door in the app. The scaffold writes a skeleton that
    // already passes the contract; the reader then edits rows and presses
    // Build below, which is why the two forms sit together.
    let newRoot = $state("");
    let newId = $state("");
    let newName = $state("");
    // One kind per line, `kind: key, key`. Free-form because an identity
    // table's shape belongs to the author's category: a fixed set of fields
    // here would be this app deciding what things are like.
    let newIdentity = $state("");
    let scaffolded = $state("");

    function parseIdentity(text: string): Record<string, string[]> {
        const out: Record<string, string[]> = {};
        for (const line of text.split("\n")) {
            const [kind, keys = ""] = line.split(":");
            const cleanKind = kind.trim();
            const cleanKeys = keys
                .split(",")
                .map((key) => key.trim())
                .filter(Boolean);
            if (cleanKind && cleanKeys.length) out[cleanKind] = cleanKeys;
        }
        return out;
    }

    const identityPreview = $derived(parseIdentity(newIdentity));
    const canScaffold = $derived(
        Boolean(newRoot.trim() && newId.trim() && newName.trim()) &&
            Object.keys(identityPreview).length > 0,
    );

    async function startPack() {
        if (!canScaffold) return;
        busy = true;
        error = null;
        scaffolded = "";
        try {
            const made = await api.scaffoldPack({
                root: newRoot.trim(),
                pack_id: newId.trim(),
                name: newName.trim(),
                identity: identityPreview,
            });
            scaffolded = made.root;
            // Hand the directory straight to the build form: the next thing
            // the reader wants is to see it install, and retyping the path
            // they just gave us would be the app forgetting on purpose.
            root = made.root;
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
        String(job.params?.subject_id ?? job.params?.root ?? "");
</script>

<h2>Jobs</h2>
<p class="lede">
    Research and pack builds run here, not in a terminal. A job keeps its log and
    its result, so a restart or a closed tab loses nothing.
</p>

<details class="authoring">
    <summary>Start a new pack</summary>
    <p class="meta">
        Writes a skeleton that already passes the pack contract — a manifest, a
        vocabulary, one placeholder subject and one placeholder claim — then hands
        the directory to the builder below. It installs nothing on its own.
    </p>
    <form class="ask stack" onsubmit={(event) => (event.preventDefault(), startPack())}>
        <label class="field">
            <span>Directory to create it in</span>
            <input bind:value={newRoot} placeholder="packs/mine" />
        </label>
        <label class="field">
            <span>Pack id</span>
            <input bind:value={newId} placeholder="org.example.mine" />
        </label>
        <label class="field">
            <span>Name</span>
            <input bind:value={newName} placeholder="What it covers, in a few words" />
        </label>
        <label class="field">
            <span>Identity keys — one kind per line, as <code>kind: key, key</code></span>
            <textarea
                bind:value={newIdentity}
                rows="3"
                placeholder={"product: brand, series\nplatform: brand, family"}
            ></textarea>
            <span class="meta">
                What makes two of these the same thing. It decides which rows can ever
                merge with another pack's, and getting it wrong fails silently rather
                than loudly — too few keys and unrelated things collide, too many and one
                thing splits across subjects that never see each other's claims.
            </span>
        </label>
        <button type="submit" disabled={busy || !canScaffold}>Write the skeleton</button>
    </form>
    {#if scaffolded}
        <p class="meta">
            Written to <code>{scaffolded}</code>. Edit the rows under
            <code>data/</code>, then build it below — the path is already filled in.
        </p>
    {/if}
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
