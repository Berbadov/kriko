<script lang="ts">
    import Async from "../lib/Async.svelte";
    import BenchChart from "../lib/BenchChart.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { follow } from "../lib/jobs";
    import { formatInterval, formatPct, formatUsd, hallucinationSeverity, pointsByLlm } from "../lib/bench";
    import type { Bench, BenchEstimate, BenchRequest, Job } from "../lib/types";

    const load = () => api.bench();
    let promise = $state(load());
    let starting = $state(false);
    let startFailure = $state<unknown>(null);
    let runningJobId = $state("");
    let stopFollow: (() => void) | undefined;
    let config = $state<BenchRequest>({ planes: "harness", cases: 3, max_documents: 3, budget_usd: 0.2, reps: 1 });
    let estimate = $state<BenchEstimate | null>(null);
    let estimatedConfig = $state("");
    let configs = $state<Record<string, BenchRequest>>({});    let gridName = $state("");
    const estimateCurrent = $derived(estimatedConfig === JSON.stringify(config));

    async function preview() {
        startFailure = null;
        const snapshot = JSON.stringify(config);
        try {
            estimate = await api.estimateBench(JSON.parse(snapshot));
            estimatedConfig = snapshot;
        } catch (cause) { startFailure = cause; }
    }

    async function savedGrids(save = false) {
        try {
            const result = save ? await api.saveBenchConfig(gridName, config) : await api.benchConfigs();
            configs = result.configs;
        } catch (cause) { startFailure = cause; }
    }

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
            const { job_id } = await api.startBench(config);
            const job = await api.job(job_id);
            watchJob(job);
        } catch (cause) {
            startFailure = cause;
        } finally {
            starting = false;
        }
    }

    $effect(() => {
        // A configs call that fails costs the saved list and nothing else:
        // the reader's grids are a convenience, and a screen that threw on
        // them would take the whole page down with it.
        api.benchConfigs().then((r) => (configs = r.configs ?? {})).catch(() => {});
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

<section class="card" aria-label="Scope the grid">
    <h3>Scope the grid</h3>
    <p class="meta">Every axis multiplies. Empty fields mean whatever this machine would pick.</p>
    <form onsubmit={(event) => (event.preventDefault(), start())}>
        <label>Planes <input bind:value={config.planes} placeholder="harness, api" /></label>
        <label>Pack <input bind:value={config.pack_id} /></label>
        <label>Cases <input type="number" min="1" max="50" bind:value={config.cases} /></label>
        <label>Sources per case <input type="number" min="1" max="20" bind:value={config.max_documents} /></label>
        <label>Reps <input type="number" min="1" max="10" bind:value={config.reps} /></label>
        <label>Ceiling $ <input type="number" min="0" max="20" step="0.01" bind:value={config.budget_usd} /></label>
        <label>LLMs <input bind:value={config.llms} placeholder="gpt-4o-mini, claude-haiku-4-5" /></label>
        <label>Search <input bind:value={config.searches} placeholder="exa, tavily" /></label>
        <label>Protocols <input bind:value={config.protocols} placeholder="standard" /></label>
    </form>
    <div class="row">
        <button onclick={preview} disabled={starting || !!runningJobId}>Estimate</button>
        <button onclick={start} disabled={starting || !!runningJobId}>
            {starting ? "Starting…" : "Run benchmark"}
        </button>
    </div>
    {#if estimate}
        <p class="meta" class:unmeasured={!estimateCurrent}>
            {estimate.runs} measurement(s){estimate.usd === null ? "" : `, about $${estimate.usd.toFixed(2)}`}
            {estimate.note ? ` — ${estimate.note}` : ""}
        </p>
    {/if}
    {#if Object.keys(configs).length}
        <details>
            <summary>Saved grids</summary>
            <ul class="strip">
                {#each Object.entries(configs) as [name, saved] (name)}
                    <li class="krow">
                        <span class="klabel">{name}</span>
                        <span class="meta">{saved.cases} case(s), planes {saved.planes || "all"}</span>
                        <button class="ghost" onclick={() => (config = { ...saved })}>Load</button>
                        <button class="ghost" onclick={() => { api.forgetBenchConfig(name).then((r) => (configs = r.configs)); }}>Forget</button>
                    </li>
                {/each}
            </ul>
        </details>
    {/if}
    <label>Save this grid as <input bind:value={gridName} /><button class="ghost" disabled={!gridName} onclick={() => savedGrids(true)}>Save</button></label>
</section>

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
