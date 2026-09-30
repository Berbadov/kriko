<script lang="ts">
    import Async from "../lib/Async.svelte";
    import DayBars from "../lib/DayBars.svelte";
    import Icon from "../lib/Icon.svelte";
    import { api } from "../lib/api";
    import { checksByDay, dayKeys, knowledgeByDay, spendByDay } from "../lib/homeSeries";

    /* Home: what this installation has done lately, as three graphs (B174).
     *
     * Counted in the browser from the rows the server already keeps
     * (`/api/operations`, `/api/jobs`), with the totals from `/api/usage`
     * beside each title. Each graph is its own section with no sentence under
     * the title; the detail is on Activity.
     */
    const DAYS = 14;
    const money = (n: number) => `$${n.toFixed(2)}`;

    async function load() {
        const days = dayKeys(DAYS);
        const [ops, jobs, usage] = await Promise.all([
            api.operations(500).catch(() => ({ items: [] })),
            api.jobs(200).catch(() => ({ items: [] })),
            api.usage().catch(() => null),
        ]);
        return {
            checks: checksByDay(ops.items ?? [], days),
            knowledge: knowledgeByDay(jobs.items ?? [], days),
            spend: spendByDay(jobs.items ?? [], days),
            totalChecks: usage?.analyses?.analyses ?? null,
            totalClaims: usage?.research?.claims ?? null,
            totalSpent: usage?.research?.spent_usd ?? null,
        };
    }
    let promise = $state(load());
</script>

<h2><Icon name="overview" size={22} /> Home</h2>

<Async {promise} loading="Reading recent activity…" retry={() => (promise = load())}>
    {#snippet children(data)}
        <div class="home-graphs">
            <section class="card">
                <h3><Icon name="verify" /> Checks</h3>
                <DayBars label="Checks" days={data.checks} />
                {#if data.totalChecks !== null}<span class="meta">{data.totalChecks} in total</span>{/if}
            </section>
            <section class="card">
                <h3><Icon name="layers" /> Knowledge gained</h3>
                <DayBars label="Claims added" days={data.knowledge} />
                {#if data.totalClaims !== null}<span class="meta">{data.totalClaims} claims in total</span>{/if}
            </section>
            <section class="card">
                <h3><Icon name="cost" /> Research spend</h3>
                {#if data.spend}
                    <DayBars label="Spend" days={data.spend} format={money} />
                {:else}
                    <span class="meta">No counted spend in this period</span>
                {/if}
                {#if data.totalSpent !== null}<span class="meta">{money(data.totalSpent)} in total</span>{/if}
            </section>
        </div>
    {/snippet}
</Async>

<style>
    .home-graphs {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: var(--s-3);
    }
</style>
