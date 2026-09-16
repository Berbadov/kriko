<script lang="ts">
    import Async from "../lib/Async.svelte";
    import BenchChart from "../lib/BenchChart.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { follow } from "../lib/jobs";
    import { formatInterval, formatPct, formatUsd, hallucinationSeverity, pointsByLlm } from "../lib/bench";
    import type { Bench, Job } from "../lib/types";

    const load = () => api.bench();
    let promise = $state(load());
    let starting = $state(false);
    let startFailure = $state<unknown>(null);
    let runningJobId = $state("");
    let stopFollow: (() => void) | undefined;

    function watchJob(job: Job) {
        runningJobId = job.job_id;
        stopFollow?.();
        stopFollow = follow(job.job_id, (updated) => {
            if (updated.done) {
                runningJobId = "";
                promise = load();
            }
        });
    }

    async function findRunningJob() {
        try {
            const { items } = await api.jobs(50);
            const running = items.find((one) => one.kind === "bench" && !one.done);
            if (running) watchJob(running);
        } catch {
            runningJobId = "";
        }
    }

    async function start() {
        starting = true;
        startFailure = null;
        try {
            const { job_id } = await api.startBench({});
            const job = await api.job(job_id);
            watchJob(job);
        } catch (cause) {
            startFailure = cause;
        } finally {
            starting = false;
        }
    }

    $effect(() => {
        void findRunningJob();
        return () => stopFollow?.();
    });
</script>

<h2>Benchmark</h2>
<p class="lede">
    At what batch size and context does each LLM stay honest, and what does a kept
    claim cost? Every row below is measured against ground truth this pack's author
    supplied, never eyeballed — a rate with no interval is a rate nobody has measured
    enough to trust yet.
</p>

{#if startFailure}<Failure error={startFailure} retry={start} />{/if}
{#if runningJobId}
    <p class="state loading">
        A benchmark is running — <a href="#/activity">watch it on Activity</a>. The
        numbers below are from the last completed run.
    </p>
{/if}

<Async {promise} loading="Reading the benchmark…" retry={() => (promise = load())}>
    {#snippet children(data: Bench)}
        {#if !data.readout.length}
            <EmptyState
                title="No benchmark runs yet"
                detail="{data.cases.length} case{data.cases.length === 1
                    ? ''
                    : 's'} would run against every configured LLM and protocol — minutes of
                    work, and real spend on a paid plane. Press Run to measure the first
                    round."
                actionLabel={starting ? "Starting…" : "Run benchmark"}
                onAction={starting ? undefined : start}
            />
        {:else}
            <table>
                <thead>
                    <tr>
                        <th scope="col">LLM</th>
                        <th scope="col">Protocol</th>
                        <th scope="col">Search</th>
                        <th scope="col" class="num">Cost / accepted claim</th>
                        <th scope="col" class="num">Hallucination rate</th>
                        <th scope="col" class="num">Runs</th>
                    </tr>
                </thead>
                <tbody>
                    {#each data.readout as row (row.llm)}
                        <tr class={row.note ? "unmeasured" : ""}>
                            <th scope="row">{row.llm}</th>
                            <td>
                                {row.protocol}
                                <div class="meta">
                                    batch {row.batch_size} · {row.context_chars.toLocaleString()} chars{row.preamble
                                        ? ` · ${row.preamble}`
                                        : ""}
                                </div>
                            </td>
                            <td>{row.search_provider || "—"}</td>
                            <td class="num">{formatUsd(row.usd_per_accepted_claim)}</td>
                            <td class="num">
                                {#if row.hallucination_rate === null}
                                    <span class="badge">not yet measured</span>
                                {:else}
                                    <span class="sev {hallucinationSeverity(row.hallucination_rate)}"
                                        >{formatPct(row.hallucination_rate)}</span
                                    >
                                    {#if row.hallucination_interval}
                                        <span class="meta">
                                            ({formatInterval(row.hallucination_interval)})
                                        </span>
                                    {/if}
                                {/if}
                            </td>
                            <td class="num">{row.runs}</td>
                        </tr>
                        {#if row.note}
                            <tr class="unmeasured">
                                <td colspan="6" class="meta">{row.note}</td>
                            </tr>
                        {/if}
                    {/each}
                </tbody>
            </table>

            <h3>Cost vs. hallucination, by protocol</h3>
            <p class="meta">
                One panel per LLM. Each point is a protocol this install has actually
                graded against ground truth; the filled point is the protocol that LLM
                would run today.
            </p>
            <div class="bench-grid">
                {#each Object.entries(pointsByLlm(data)) as [llm, points] (llm)}
                    <BenchChart {llm} {points} />
                {/each}
            </div>

            <div class="row">
                <button onclick={start} disabled={starting || !!runningJobId}>
                    {starting ? "Starting…" : "Run benchmark again"}
                </button>
            </div>
        {/if}
    {/snippet}
</Async>

<style>
    .bench-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: var(--s-3);
        margin-block: var(--s-3);
    }
    tr.unmeasured {
        opacity: 0.65;
    }
    .row {
        margin-block-start: var(--s-4);
    }
</style>
