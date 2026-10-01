<script lang="ts">
    import Async from "../lib/Async.svelte";
    import DayBars from "../lib/DayBars.svelte";
    import Icon from "../lib/Icon.svelte";
    import PageHead from "../lib/kriko/PageHead.svelte";
    import Key from "../lib/kriko/Key.svelte";
    import { api } from "../lib/api";
    import { checksByDay, dayKeys, knowledgeByDay, spendByDay } from "../lib/homeSeries";
    import { toHash } from "../lib/router";
    import type { HistoryItem } from "../lib/types";
    /* Home: what this installation has done lately, as three graphs (B174),
     * in the design system's page frame (kriko-svelte/pages/Home.svelte).
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
        const [ops, jobs, usage, history] = await Promise.all([
            api.operations(500).catch(() => ({ items: [] })),
            api.jobs(200).catch(() => ({ items: [] })),
            api.usage().catch(() => null),
            api.history(5).catch(() => ({ items: [] as HistoryItem[] })),
        ]);
        return {
            checks: checksByDay(ops.items ?? [], days),
            knowledge: knowledgeByDay(jobs.items ?? [], days),
            spend: spendByDay(jobs.items ?? [], days),
            totalChecks: usage?.analyses?.analyses ?? null,
            totalClaims: usage?.research?.claims ?? null,
            totalSpent: usage?.research?.spent_usd ?? null,
            recent: (history.items ?? []).slice(0, 5),
        };
    }
    let promise = $state(load());
</script>

<PageHead crumb="home" title="Home" lead="Check a product, resume a run, or see what Kriko already knows." />

<Async {promise} loading="Reading recent activity…" retry={() => (promise = load())}>
    {#snippet children(data)}
        <div class="k-grid k-g3" style="margin-bottom: 24px">
            <section class="k-card">
                <div class="k-eyebrow" style="margin-bottom: 12px">Checks</div>
                <DayBars label="Checks" days={data.checks} />
                {#if data.totalChecks !== null}
                    <span class="k-note">{data.totalChecks} in total</span>
                {/if}
            </section>
            <section class="k-card">
                <div class="k-eyebrow" style="margin-bottom: 12px">Knowledge gained</div>
                <DayBars label="Claims added" days={data.knowledge} />
                {#if data.totalClaims !== null}
                    <span class="k-note">{data.totalClaims} claims in total</span>
                {/if}
            </section>
            <section class="k-card">
                <div class="k-eyebrow" style="margin-bottom: 12px">Research spend</div>
                {#if data.spend}
                    <DayBars label="Spend" days={data.spend} format={money} />
                {:else}
                    <span class="k-note">No counted spend in this period</span>
                {/if}
                {#if data.totalSpent !== null}
                    <span class="k-note">{money(data.totalSpent)} in total</span>
                {/if}
            </section>
        </div>

        <div class="k-card">
            <h2><Icon name="history" size={18} /> Recent checks</h2>
            {#if data.recent.length}
                <table class="k-table">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>When</th>
                            <th class="r"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each data.recent as item (item.lookup_id)}
                            <tr>
                                <td>
                                    <a href={toHash("result", item.lookup_id)}>{item.label}</a>
                                </td>
                                <td class="m">{item.created_at}</td>
                                <td class="r"><Key variant="plate">Open</Key></td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {:else}
                <span class="k-note">No check yet. The browser extension is where one starts.</span>
            {/if}
        </div>
    {/snippet}
</Async>

<style>
    .k-card .k-note {
        display: inline-block;
        margin-top: 8px;
    }
</style>
