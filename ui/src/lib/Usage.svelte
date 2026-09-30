<script lang="ts">
    import Icon from "./Icon.svelte";
    import { count as plural } from "./plural";
    import Async from "./Async.svelte";
    import { api } from "./api";
    import type { Usage, UsageTotals } from "./types";

    /* What this installation has spent, and what it was asked. (B97)
     *
     * The reader's complaint was "I see no token info, no usage info etc.",
     * and it was accurate: every number below existed somewhere and none of
     * it was ever rendered. The runs list said what *one* run cost; the
     * analyses log — the record of every lookup ever made here — had its
     * path on the About screen and no reader of its contents.
     *
     * Two rules the whole panel is built on:
     *
     * * **A number nobody measured is not shown as zero.** `null` reaches
     *   this component and comes out as "not counted", because "cost
     *   nothing" and "nobody measured" are different answers and only one of
     *   them is a figure a reader can repeat. The `$0.00` this panel refuses
     *   to render is the one number that would be quoted back at us.
     * * **Every total carries its denominator.** `metered_runs of runs` sits
     *   beside the spend, so a small total over many runs cannot be mistaken
     *   for a cheap installation.
     */

    /* Nulls, not zeros, for the metered columns: an absent half of the
     * payload is unmeasured, and this panel's first rule is that unmeasured
     * does not render as a measured zero. */
    const EMPTY: Usage = {
        research: {
            runs: 0,
            metered_runs: 0,
            counted_runs: 0,
            spent_usd: null,
            tokens_used: null,
            claims: 0,
            cost_per_claim: null,
            planes: [],
        },
        analyses: {
            analyses: 0,
            malformed: 0,
            claims_shown: 0,
            answered_nothing: 0,
            subjects: 0,
            adapters: [],
        },
    };

    /** Every field this card reads, present whatever arrived. */
    const shape = (raw: Partial<Usage> | undefined): Usage => ({
        research: { ...EMPTY.research, ...(raw?.research ?? {}) },
        analyses: { ...EMPTY.analyses, ...(raw?.analyses ?? {}) },
    });

    let promise = $state(api.usage());
    const refresh = () => (promise = api.usage());

    const money = (value: number | null, digits = 2) =>
        value === null ? "not counted" : `$${value.toFixed(digits)}`;

    const count = (value: number | null) =>
        value === null ? "not counted" : value.toLocaleString();

    /** The plane in the reader's words. Same mapping as the runs list, and
     *  deliberately not imported from it — that one is about a single run's
     *  provenance and names the completion API behind it; this is a row
     *  label for a whole plane's total. */
    const PLANE: Record<string, string> = {
        agent: "Your agent, by hand",
        harness: "Your agent, started by Kriko",
        api: "Kriko itself, per token",
    };

    /** Why a spend column is empty, in one clause. A blank cell reads as a
     *  bug; "no marginal cost" is the actual answer for two of three planes. */
    const unmetered = (row: UsageTotals["planes"][number]) =>
        row.plane === "api"
            ? "not counted"
            : "no marginal cost — your subscription paid for it";
</script>

<section class="usage">
    <h3><Icon name="cost" /> What this has used</h3>
    <p class="meta">
        Every research run that wrote knowledge in, and every lookup that read it
        back out. A plane that cannot count leaves its column empty rather than
        claiming a measured zero.
    </p>

    <Async {promise} loading="Adding it up…" retry={refresh}>
        {#snippet children(raw: Usage)}
            <!-- Filled in rather than trusted. A payload missing a half is a
                 payload from an older engine, and a template that reads
                 `.planes.length` off an absent half takes the whole card
                 down — which is a worse answer to "what did this cost" than
                 four dashes. -->
            {@const data = shape(raw)}
            <dl class="totals">
                <div>
                    <dt>Spent</dt>
                    <dd>
                        {money(data.research.spent_usd, 4)}
                        <span class="meta"
                            >{data.research.metered_runs} of {data.research.runs}
                            run{data.research.runs === 1 ? "" : "s"} counted</span
                        >
                    </dd>
                </div>
                <div>
                    <dt>Tokens</dt>
                    <dd>
                        {count(data.research.tokens_used)}
                        <span class="meta"
                            >across {data.research.counted_runs} run{data.research
                                .counted_runs === 1
                                ? ""
                                : "s"} that could count</span
                        >
                    </dd>
                </div>
                <div>
                    <dt>Per claim</dt>
                    <dd>
                        {money(data.research.cost_per_claim, 4)}
                        <span class="meta"
                            >{data.research.claims} claim{data.research.claims === 1
                                ? ""
                                : "s"} still in the store</span
                        >
                    </dd>
                </div>
                <div>
                    <dt>Looked up</dt>
                    <dd>
                        {data.analyses.analyses.toLocaleString()}
                        <span class="meta"
                            >{data.analyses.answered_nothing} came back with nothing</span
                        >
                    </dd>
                </div>
            </dl>

            {#if data.research.planes.length}
                <table>
                    <thead>
                        <tr>
                            <th scope="col">Plane</th>
                            <th scope="col">Runs</th>
                            <th scope="col">Tokens</th>
                            <th scope="col">Spent</th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each data.research.planes as row (row.plane)}
                            <tr>
                                <th scope="row">{PLANE[row.plane] ?? (row.plane || "—")}</th>
                                <td>{row.runs}</td>
                                <td>{count(row.tokens_used)}</td>
                                <td
                                    >{row.spent_usd === null
                                        ? unmetered(row)
                                        : money(row.spent_usd, 4)}</td
                                >
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {:else}
                <p class="state empty">
                    Nothing has run here yet, so there is nothing to add up. The
                    three planes are on <a href="#/agents">Agents</a>.
                </p>
            {/if}

            {#if data.analyses.malformed}
                <p class="state warn">
                    {plural(data.analyses.malformed, "line")} of the analyses log could not be
                    read and were skipped. Nothing else is affected — the log is
                    append-only and a bad line costs only itself.
                </p>
            {/if}
        {/snippet}
    </Async>
</section>

<style>
    .usage {
        margin-block-start: var(--s-5);
    }
    .usage > .meta {
        max-width: var(--measure);
    }
    .totals {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
        gap: var(--s-3);
        margin: var(--s-4) 0;
    }
    .totals dt {
        font-size: var(--fs-0);
        color: var(--ink-2);
    }
    .totals dd {
        margin: 0;
        font-size: var(--fs-3);
        font-variant-numeric: tabular-nums;
    }
    .totals .meta {
        display: block;
        font-size: var(--fs-0);
    }
    table {
        width: 100%;
        border-collapse: collapse;
        font-variant-numeric: tabular-nums;
    }
    th[scope="col"] {
        text-align: left;
        font-size: var(--fs-0);
        color: var(--ink-2);
        border-block-end: 1px solid var(--line);
    }
    th[scope="row"] {
        text-align: left;
        font-weight: 400;
    }
    td,
    th {
        padding: var(--s-2) var(--s-2) var(--s-2) 0;
    }
    tbody tr + tr th,
    tbody tr + tr td {
        border-block-start: 1px solid var(--line);
    }
</style>
