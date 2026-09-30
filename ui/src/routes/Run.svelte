<script lang="ts">
    import { tick } from "svelte";
    import Icon from "../lib/Icon.svelte";
    import Failure from "../lib/Failure.svelte";
    import RunPanel from "../lib/RunPanel.svelte";
    import RunWith from "../lib/RunWith.svelte";
    import SourceSlider from "../lib/SourceSlider.svelte";
    import { api } from "../lib/api";
    import { follow, isLive } from "../lib/jobs";
    import { agentOf } from "../lib/live";
    import { hashWith } from "../lib/router";
    import type { HarnessModel, Job } from "../lib/types";

    /* Start a run, and watch it (B175, B176).
     *
     * One compact form on top and the dark panel under it. It was the top of
     * Activity's Runs lens ("Start a new pack", under a paragraph), and a
     * reader who pressed the button then had to scroll a list of every job
     * the installation had ever run to find the one they had just started.
     * Here the run they started is the panel under the button.
     *
     * One field, because an agent that has read the category decides the
     * rest better than a reader who has not (D4, `AuthorRequest`). Which
     * agent, which LLM, how long and how many sources are dials beside it
     * and never required. The category field is autofocused, and App's
     * `focusTheView()` reads the attribute to decide who gets focus.
     *
     * Every live job is shown, not only the one started here: an agent
     * working through the MCP server, or a run started from the extension,
     * is also "a run that is going" and was invisible on this screen.
     */
    const CATEGORY_MIN = 2;
    const TIMEOUTS = [
        { seconds: 0, label: "40 min (default)" },
        { seconds: 600, label: "10 min" },
        { seconds: 1200, label: "20 min" },
        { seconds: 3600, label: "60 min" },
    ];

    let category = $state("");
    let harness = $state("");
    let timeout = $state(0);
    let sources = $state(0);
    let busy = $state(false);
    let error = $state<unknown>(null);
    let jobs = $state<Job[]>([]);
    let installed = $state<HarnessModel[]>([]);
    let preferred = $state("");
    let now = $state(Date.now());

    const stops = new Map<string, () => void>();

    // A run finishes and the server stops sending its feed; the panel keeps
    // the last one it had, so a finished run still says what it did.
    const replace = (job: Job) => {
        const at = jobs.findIndex((one) => one.job_id === job.job_id);
        if (at === -1) jobs = [job, ...jobs];
        else jobs[at] = { ...job, feed: job.feed ?? jobs[at].feed };
        if (job.done) {
            stops.get(job.job_id)?.();
            stops.delete(job.job_id);
        }
    };

    const watch = (job: Job) => {
        if (!isLive(job) || stops.has(job.job_id)) return;
        stops.set(job.job_id, follow(job.job_id, replace));
    };

    // Only what is going. The list of everything that ever ran is Activity's.
    const adopt = async () => {
        try {
            const seen = new Set(jobs.map((one) => one.job_id));
            const live = ((await api.jobs()).items ?? []).filter(isLive);
            for (const job of live) {
                if (seen.has(job.job_id)) continue;
                jobs = [job, ...jobs];
                watch(job);
            }
        } catch {
            // A missed poll costs nothing; the next one retries.
        }
    };

    $effect(() => {
        void adopt();
        api.prefs()
            .then((data) => {
                installed = data.harnesses ?? [];
                preferred = data.chosen?.preferred_harness ?? "";
            })
            .catch(() => {});
        const slow = setInterval(() => void adopt(), 4000);
        const clock = setInterval(() => (now = Date.now()), 1000);
        return () => {
            clearInterval(slow);
            clearInterval(clock);
            stops.forEach((stop) => stop());
            stops.clear();
        };
    });

    async function start() {
        if (category.trim().length < CATEGORY_MIN || busy) return;
        busy = true;
        error = null;
        try {
            const { job_id } = await api.authorPack(category.trim(), harness, timeout, sources);
            const job = await api.job(job_id);
            replace(job);
            watch(job);
            await tick();
        } catch (cause) {
            error = cause;
        } finally {
            busy = false;
        }
    }

    const ready = $derived(category.trim().length >= CATEGORY_MIN && !busy);
    const live = $derived(jobs.filter(isLive));
    const finished = $derived(jobs.filter((one) => !isLive(one)));
</script>

<h2><Icon name="jobs" size={22} /> Run</h2>

<form class="card form" onsubmit={(event) => (event.preventDefault(), start())}>
    <div class="ask">
        <label class="field grow">
            <span>Category</span>
            <!-- svelte-ignore a11y_autofocus -- deliberate: this screen has
                 one field and the reader came to fill it. -->
            <input
                bind:value={category}
                placeholder="cordless drills, espresso machines, e-bikes"
                autocomplete="off"
                autofocus
            />
        </label>
        <button class="primary" type="submit" disabled={!ready}>
            {busy ? "Starting" : "Start"}
        </button>
    </div>
    <RunWith bind:harness bind:timeout timeouts={TIMEOUTS} disabled={busy} />
    <SourceSlider bind:value={sources} disabled={busy} />
</form>

{#if error}
    <Failure {error} retry={start} />
{/if}

<div class="stage" aria-label="Runs">
    {#each [...live, ...finished] as job (job.job_id)}
        <RunPanel {job} {now} agent={agentOf(job, preferred, installed)} />
    {:else}
        <div class="idle" role="status">
            <span class="meta">No run is going</span>
            <a href={hashWith({ lens: "runs" }, "activity")}>All runs</a>
        </div>
    {/each}
</div>

<style>
    .form {
        margin-block-end: var(--s-4);
    }
    .ask {
        display: flex;
        gap: var(--s-3);
        align-items: flex-end;
        flex-wrap: wrap;
    }
    .grow {
        flex: 1 1 16rem;
    }
    .stage {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    .idle {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: var(--n-0);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: var(--s-3);
    }
</style>
