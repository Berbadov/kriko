<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import { tick } from "svelte";
    import { api } from "../lib/api";
    import { count } from "../lib/plural";
    import Failure from "../lib/Failure.svelte";
    import JackMark from "../lib/kriko/JackMark.svelte";
    import { signalNote, tieNote } from "../lib/health";
    import { hashWith } from "../lib/router";
    import type { ClaimHealth, HealthTree } from "../lib/types";

    // Its own page once, now one lens inside Knowledge. The heading is a
    // prop rather than always-on because a second <h2> inside a screen that
    // already has one reads as two pages stacked.
    //
    // `focusClaimId`: a link from elsewhere (Overview's "Thinnest evidence")
    // names a claim rather than dumping the reader on the top of the list —
    // see openFocused below.
    let { heading = true, focusClaimId = "" }: { heading?: boolean; focusClaimId?: string } =
        $props();

    let claims = $state<ClaimHealth[]>([]);
    let tree = $state<HealthTree | null>(null);
    let askedClaimId = $state("");
    // The exception itself, not its message: Failure needs the status to
    // know what the reader can do about it, and a string has already
    // thrown that away.
    let failure = $state<unknown>(null);
    // Evidence's own failure, kept apart from the table's: a broken tree
    // fetch must not blank out the 40 rows the reader can still read.
    let treeFailure = $state<unknown>(null);
    let cardEl = $state<HTMLElement | null>(null);

    async function load() {
        try {
            claims = (await api.weakest(40)).claims;
            failure = null;
        } catch (e) {
            failure = e;
        }
    }

    async function openTree(claim: ClaimHealth) {
        tree = null;
        treeFailure = null;
        askedClaimId = claim.claim_id;
        try {
            tree = await api.healthSubject(claim.subject_id);
        } catch (e) {
            treeFailure = e;
            return;
        }
        // Pressing Evidence used to render the card after the whole table —
        // off the bottom of a 40-row list, so the button looked dead. Scroll
        // it into view and move focus there, the same as opening it any
        // other way.
        await tick();
        cardEl?.scrollIntoView({ block: "start" });
        cardEl?.focus();
    }

    const ready = load().then(() => {
        if (!focusClaimId) return;
        const claim = claims.find((c) => c.claim_id === focusClaimId);
        if (claim) void openTree(claim);
    });
</script>

{#if heading}<h2><Icon name="activity" size={22} /> Claim health</h2>{/if}
<p class="meta">
    The weakest-supported claims we ship, worst first. Contradicted, then fewest
    independent sources, then weakest best source, then stalest. No combined score; each
    signal is its own column.
    <em>Independence and stance are flags the pack author supplied, not verified facts.</em>
    Claims with no sources at all are not listed here; that is a coverage question, answered
    by <a href={hashWith({ lens: "gaps" }, "knowledge")}>What is missing</a>, not a weakness one.
</p>
{#if tieNote(claims)}<p class="meta">{tieNote(claims)}</p>{/if}

{#await ready}
    <p class="state loading loading-mark"><JackMark />Loading…</p>
{:then}
    {#if failure}
        <Failure error={failure} retry={load} />
    {:else if !claims.length}
        <p class="state empty">No sourced claims installed yet.</p>
    {:else}
        <div class="table-scroll">
            <table>
                <thead>
                    <tr>
                        <th>Claim</th><th>Contradicted</th><th>Independent sources</th>
                        <th>Best source</th><th>Last retrieved</th><th></th>
                    </tr>
                </thead>
                <tbody>
                    {#each claims as claim (claim.claim_id)}
                        <tr class={claim.refuted_by > 0 ? "concern" : ""}>
                            <td>
                                {claim.title}
                                <div class="meta">{claim.subject_label} · {claim.pack_id}</div>
                                {#if signalNote(claim)}
                                    <div class="meta">{signalNote(claim)}</div>
                                {/if}
                            </td>
                            <td class="num signal">
                                {#if claim.refuted_by > 0}
                                    <span class="badge">{claim.refuted_by} refuting</span>
                                {:else}·{/if}
                            </td>
                            <td class="num signal">{claim.independent_sources}</td>
                            <td class="signal">
                                {claim.best_tier}
                                <span class="meta">{claim.best_trust.toFixed(2)}</span>
                            </td>
                            <td class="signal {claim.oldest_retrieved_at ? '' : 'stale'}">
                                {claim.oldest_retrieved_at || "unknown"}
                            </td>
                            <td><button onclick={() => openTree(claim)}>Evidence</button></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>

        {#if treeFailure}
            <Failure error={treeFailure} retry={() => {
                const claim = claims.find((c) => c.claim_id === askedClaimId);
                if (claim) void openTree(claim);
            }} />
        {/if}

        {#if tree}
            <article class="card" bind:this={cardEl} tabindex="-1">
                <h3>
                    {tree.label ?? "Subject"}
                    <span class="badge">{count(tree.claims.length, "claim")}</span>
                </h3>
                {#each tree.claims as node (node.health.claim_id)}
                    {@const asked = node.health.claim_id === askedClaimId}
                    <details open={asked} class={asked ? "asked" : ""}>
                        <summary>
                            {#if asked}<span class="badge">Asked about</span>{/if}
                            {node.health.title}
                            <span class="meta">
                                {count(node.health.independent_sources, "source")} · {node.health
                                    .best_tier}
                            </span>
                        </summary>
                        {#if node.evidence.length}
                            {#each node.evidence as row}
                                <blockquote class={row.stance === "refutes" ? "refutes" : ""}>
                                    {row.quote}
                                    <footer class="meta">
                                        {row.domain} · {row.tier} · {row.stance}{row.independent
                                            ? ""
                                            : " · not independent"} · retrieved {row.retrieved_at ||
                                            "unknown"}
                                    </footer>
                                </blockquote>
                            {/each}
                        {:else}
                            <p class="state empty">
                                No sources; this claim rests on an interval or a rule, not a
                                citation.
                            </p>
                        {/if}
                    </details>
                {/each}
            </article>
        {/if}
    {/if}
{/await}
