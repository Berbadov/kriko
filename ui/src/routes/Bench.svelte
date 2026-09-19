<script lang="ts">
    import Async from "../lib/Async.svelte";
    import BenchChart from "../lib/BenchChart.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { follow } from "../lib/jobs";
    import { formatInterval, formatPct, formatUsd, hallucinationSeverity, pointsByLlm } from "../lib/bench";
    import type { Bench, BenchEstimate, BenchRequest, Job } from "../lib/types";

    type OfferedLlm = { id: string; label: string; provider: string; unusable: string };
    type SearchChoice = { id: string; label: string; ready: boolean };
    type PrefsView = { models?: { offered?: OfferedLlm[] }; search_providers?: SearchChoice[] };
    type ScalePreset = { id: string; label: string; max_documents: number; blurb: string };

    const PLANE_CHOICES = ["harness", "agent", "api"];
    const SCALE_PRESETS: ScalePreset[] = [
        { id: "quick", label: "Quick", max_documents: 3, blurb: "3 sources per case" },
        { id: "standard", label: "Standard", max_documents: 7, blurb: "7 sources per case" },
        { id: "deep", label: "Deep", max_documents: 15, blurb: "15 sources per case" },
    ];
    const SEARCH_FALLBACK: SearchChoice[] = [
        { id: "exa", label: "Exa", ready: true },
        { id: "tavily", label: "Tavily", ready: true },
    ];
    const BUDGET_STEP = 0.05;
    const BUDGET_MIN = 0;
    const BUDGET_MAX = 20;
    const REPS_MIN = 1;
    const REPS_MAX = 10;
    const CASES_MIN = 1;
    const CASES_MAX = 50;

    const load = () => api.bench();
    let promise = $state(load());
    let benchData = $state<Bench | null>(null);
    let prefsView = $state<PrefsView | null>(null);
    let starting = $state(false);
    let startFailure = $state<unknown>(null);
    let estimateError = $state<unknown>(null);
    let runningJobId = $state("");
    let stopFollow: (() => void) | undefined;
    let planesSel = $state<string[]>(["harness"]);
    let llmsSel = $state<string[]>([]);
    let searchesSel = $state<string[]>([]);
    let protocolsSel = $state<string[]>([]);
    let scaleId = $state("quick");
    let packId = $state("");
    let casesCount = $state(3);
    let repsCount = $state(1);
    let budgetVal = $state(0.2);
    let estimate = $state<BenchEstimate | null>(null);
    let estimatedKey = $state("");
    let configs = $state<Record<string, BenchRequest>>({});
    let gridName = $state("");
    let touched = $state(false);
    let estimateTimer: ReturnType<typeof setTimeout> | undefined;

    const docsForScale = (id: string) => SCALE_PRESETS.find((one) => one.id === id)?.max_documents ?? 3;
    const requestBody = $derived<BenchRequest>({
        planes: planesSel.join(", "),
        pack_id: packId,
        cases: casesCount,
        max_documents: docsForScale(scaleId),
        budget_usd: budgetVal,
        protocols: protocolsSel.join(", "),
        reps: repsCount,
        llms: llmsSel.join(", "),
        searches: searchesSel.join(", "),
    });
    const requestKey = $derived(JSON.stringify(requestBody));
    const estimateCurrent = $derived(estimatedKey === requestKey);
    const protocolOptions = $derived(benchData?.protocols ?? []);
    const packOptions = $derived([...new Set((benchData?.cases ?? []).map((one) => String((one as Record<string, unknown>).pack_id ?? "")).filter(Boolean))]);
    const offeredLlms = $derived(prefsView?.models?.offered ?? []);
    const searchOptions = $derived(prefsView?.search_providers?.length ? prefsView.search_providers : SEARCH_FALLBACK);

    function toggle(sel: string[], value: string): string[] {
        touched = true;
        return sel.includes(value) ? sel.filter((one) => one !== value) : [...sel, value];
    }

    function splitList(value: unknown): string[] {
        if (Array.isArray(value)) return value.map(String).map((one) => one.trim()).filter(Boolean);
        return String(value ?? "").split(",").map((one) => one.trim()).filter(Boolean);
    }

    function clampCount(value: unknown, lo: number, hi: number, fallback: number): number {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) return fallback;
        return Math.min(hi, Math.max(lo, Math.round(parsed)));
    }

    function loadGrid(name: string) {
        const saved = configs[name];
        if (!saved) return;
        const raw = saved as unknown as Record<string, unknown>;
        planesSel = splitList(raw.planes);
        llmsSel = splitList(raw.llms ?? raw.models);
        searchesSel = splitList(raw.searches ?? raw.search);
        protocolsSel = splitList(raw.protocols);
        packId = String(raw.pack_id ?? "");
        casesCount = clampCount(raw.cases, CASES_MIN, CASES_MAX, 3);
        repsCount = clampCount(raw.reps, REPS_MIN, REPS_MAX, 1);
        const dollars = Number(raw.budget_usd);
        budgetVal = Number.isFinite(dollars) ? Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, Math.round(dollars * 100) / 100)) : 0.2;
        const docs = Number(raw.max_documents ?? 3);
        const exact = SCALE_PRESETS.find((one) => one.max_documents === docs);
        scaleId = exact?.id ?? (docs <= 3 ? "quick" : docs <= 7 ? "standard" : "deep");
        touched = true;
    }

    function bumpReps(delta: number) {
        touched = true;
        repsCount = Math.min(REPS_MAX, Math.max(REPS_MIN, repsCount + delta));
    }

    function bumpCases(delta: number) {
        touched = true;
        casesCount = Math.min(CASES_MAX, Math.max(CASES_MIN, casesCount + delta));
    }

    function bumpBudget(delta: number) {
        touched = true;
        budgetVal = Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, Math.round((budgetVal + delta) * 100) / 100));
    }

    async function preview(explicit: boolean) {
        if (explicit) estimateError = null;
        const snapshot = JSON.stringify(requestBody);
        try {
            const result = await api.estimateBench(JSON.parse(snapshot));
            if (typeof (result as BenchEstimate)?.runs === "number") {
                estimate = result as BenchEstimate;
                estimatedKey = snapshot;
            }
        } catch (cause) {
            if (explicit) estimateError = cause;
        }
    }

    async function savedGrids(save = false) {
        try {
            const result = save ? await api.saveBenchConfig(gridName, requestBody) : await api.benchConfigs();
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
            const { job_id } = await api.startBench(JSON.parse(JSON.stringify(requestBody)));
            const job = await api.job(job_id);
            watchJob(job);
        } catch (cause) {
            startFailure = cause;
        } finally {
            starting = false;
        }
    }

    $effect(() => {
        api.bench().then((data) => (benchData = data)).catch(() => {});
        api.prefs().then((data) => (prefsView = data as unknown as PrefsView)).catch(() => {});
        api.benchConfigs().then((r) => (configs = r.configs ?? {})).catch(() => {});
        void findRunningJob();
        return () => stopFollow?.();
    });

    $effect(() => {
        if (!touched) return;
        const key = requestKey;
        clearTimeout(estimateTimer);
        estimateTimer = setTimeout(() => {
            void preview(false).then(() => undefined, () => undefined).finally(() => undefined);
            void key;
        }, 350);
        return () => clearTimeout(estimateTimer);
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
    <p class="meta">Every axis multiplies. Nothing selected means whatever this machine would pick.</p>
    <fieldset>
        <legend>Planes</legend>
        <div class="chips">
            {#each PLANE_CHOICES as plane (plane)}
                <button type="button" aria-pressed={planesSel.includes(plane)} onclick={() => (planesSel = toggle(planesSel, plane))}>{plane}</button>
            {/each}
        </div>
        {#if !planesSel.length}<p class="meta">None selected — whatever this machine can run.</p>{/if}
    </fieldset>
    <fieldset>
        <legend>Pack</legend>
        <select aria-label="Pack" value={packId} onchange={(event) => { touched = true; packId = event.currentTarget.value; }}>
            <option value="">Every pack</option>
            {#each packOptions as pack (pack)}
                <option value={pack}>{pack}</option>
            {/each}
        </select>
    </fieldset>
    <fieldset>
        <legend>Scale</legend>
        <div class="chips">
            {#each SCALE_PRESETS as preset (preset.id)}
                <button type="button" aria-pressed={scaleId === preset.id} title={preset.blurb} onclick={() => { touched = true; scaleId = preset.id; }}>{preset.label}</button>
            {/each}
        </div>
        <p class="meta">{SCALE_PRESETS.find((one) => one.id === scaleId)?.blurb ?? ""}</p>
    </fieldset>
    <fieldset>
        <legend>Cases</legend>
        <div class="stepper">
            <button type="button" aria-label="Fewer cases" disabled={casesCount <= CASES_MIN} onclick={() => bumpCases(-1)}>−</button>
            <output aria-live="polite">{casesCount}</output>
            <button type="button" aria-label="More cases" disabled={casesCount >= CASES_MAX} onclick={() => bumpCases(1)}>+</button>
        </div>
    </fieldset>
    <fieldset>
        <legend>Repetitions</legend>
        <div class="stepper">
            <button type="button" aria-label="Fewer repetitions" disabled={repsCount <= REPS_MIN} onclick={() => bumpReps(-1)}>−</button>
            <output aria-live="polite">{repsCount}</output>
            <button type="button" aria-label="More repetitions" disabled={repsCount >= REPS_MAX} onclick={() => bumpReps(1)}>+</button>
        </div>
    </fieldset>
    <fieldset>
        <legend>Ceiling per case</legend>
        <div class="stepper">
            <button type="button" aria-label="Lower ceiling" disabled={budgetVal <= BUDGET_MIN} onclick={() => bumpBudget(-BUDGET_STEP)}>−</button>
            <output aria-live="polite">${budgetVal.toFixed(2)}</output>
            <button type="button" aria-label="Raise ceiling" disabled={budgetVal >= BUDGET_MAX} onclick={() => bumpBudget(BUDGET_STEP)}>+</button>
        </div>
    </fieldset>
    <fieldset>
        <legend>LLMs</legend>
        {#if offeredLlms.length}
            <div class="chips">
                {#each offeredLlms as one (one.id)}
                    <button type="button" disabled={!!one.unusable} title={one.unusable || one.provider} aria-pressed={llmsSel.includes(one.id)} onclick={() => (llmsSel = toggle(llmsSel, one.id))}>{one.label}</button>
                {/each}
            </div>
            {#if !llmsSel.length}<p class="meta">None selected — whichever this installation would pick.</p>{/if}
        {:else}
            <p class="meta">The catalogue offered nothing — check Settings → Research.</p>
        {/if}
    </fieldset>
    <fieldset>
        <legend>Search</legend>
        <div class="chips">
            {#each searchOptions as one (one.id)}
                <button type="button" disabled={!one.ready} title={one.ready ? one.label : `${one.label} — no key set`} aria-pressed={searchesSel.includes(one.id)} onclick={() => (searchesSel = toggle(searchesSel, one.id))}>{one.label}</button>
            {/each}
        </div>
        {#if !searchesSel.length}<p class="meta">None selected — whichever has a key.</p>{/if}
    </fieldset>
    <fieldset>
        <legend>Protocols</legend>
        {#if protocolOptions.length}
            <div class="chips">
                {#each protocolOptions as one (one.name)}
                    <button type="button" aria-pressed={protocolsSel.includes(one.name)} onclick={() => (protocolsSel = toggle(protocolsSel, one.name))}>{one.name}</button>
                {/each}
            </div>
            {#if !protocolsSel.length}<p class="meta">None selected — whatever the plane would choose.</p>{/if}
        {:else}
            <p class="meta">No protocols measured yet — the plane chooses.</p>
        {/if}
    </fieldset>
    <div class="row">
        <button onclick={() => preview(true)} disabled={starting || !!runningJobId}>Estimate</button>
        <button onclick={start} disabled={starting || !!runningJobId}>
            {starting ? "Starting…" : "Run benchmark"}
        </button>
    </div>
    {#if estimate && typeof estimate.runs === "number"}
        <p class="meta" class:unmeasured={!estimateCurrent}>
            {estimate.runs} measurement(s){estimate.usd === null || estimate.usd === undefined ? " — not yet measured here" : `, about $${estimate.usd.toFixed(2)}`}
            {estimate.note ? ` — ${estimate.note}` : ""}
        </p>
    {/if}
    {#if estimateError}<p class="state">The estimate failed — the grid above is unchanged.</p>{/if}
    {#if Object.keys(configs).length}
        <details>
            <summary>Saved grids</summary>
            <ul class="strip">
                {#each Object.entries(configs) as [name, saved] (name)}
                    <li class="krow">
                        <span class="klabel">{name}</span>
                        <span class="meta">{saved.cases} case(s), planes {saved.planes || "all"}</span>
                        <button class="ghost" onclick={() => loadGrid(name)}>Load</button>
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
    .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
    }
    .chips button[aria-pressed="true"] {
        outline: 2px solid currentColor;
    }
    .stepper {
        display: inline-flex;
        align-items: center;
        gap: 0.6rem;
    }
    fieldset {
        margin-block: 0.7rem;
    }
</style>
