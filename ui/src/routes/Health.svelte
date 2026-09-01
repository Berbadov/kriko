<script lang="ts">
    import { api } from "../lib/api";
    import { signalNote, tieNote } from "../lib/health";
    import type { ClaimHealth, HealthTree } from "../lib/types";

    let claims = $state<ClaimHealth[]>([]);
    let tree = $state<HealthTree | null>(null);
    let askedClaimId = $state("");
    let error = $state("");

    async function load() {
        try {
            claims = (await api.weakest(40)).claims;
        } catch (e) {
            error = (e as Error).message;
        }
    }

    async function openTree(claim: ClaimHealth) {
        askedClaimId = claim.claim_id;
        tree = await api.healthSubject(claim.subject_id);
    }

    const ready = load();
</script>

<h2>Claim health</h2>
<p class="meta">
    The weakest-supported claims we ship, worst first. Contradicted, then fewest
    independent sources, then weakest best source, then stalest. No combined score — each
    signal is its own column.
    <em>Independence and stance are flags the pack author supplied, not verified facts.</em>
    Claims with no sources at all are not listed here — that is a coverage question, answered
    by the Coverage tab, not a weakness one.
</p>
{#if tieNote(claims)}<p class="meta">{tieNote(claims)}</p>{/if}

{#await ready}
    <p class="state loading">Loading…</p>
{:then}
    {#if error}
        <p class="state error">Could not load this view: {error}</p>
    {:else if !claims.length}
        <p class="state empty">No sourced claims installed yet.</p>
    {:else}
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
                            {:else}—{/if}
                        </td>
                        <td class="num signal">{claim.independent_sources}</td>
                        <td class="signal">
                            {claim.best_tier}
                            <span class="meta">{claim.best_trust.toFixed(2)}</span>
                        </td>
                        <td class="signal {claim.oldest_retrieved_at ? '' : 'stale'}">
                            {claim.oldest_retrieved_at ?? "unknown"}
                        </td>
                        <td><button onclick={() => openTree(claim)}>Evidence</button></td>
                    </tr>
                {/each}
            </tbody>
        </table>

        {#if tree}
            <article class="card">
                <h3>
                    {tree.label ?? "Subject"}
                    <span class="badge">{tree.claims.length} claim(s)</span>
                </h3>
                {#each tree.claims as node (node.health.claim_id)}
                    {@const asked = node.health.claim_id === askedClaimId}
                    <details open={asked} class={asked ? "asked" : ""}>
                        <summary>
                            {#if asked}<span class="badge">Asked about</span>{/if}
                            {node.health.title}
                            <span class="meta">
                                {node.health.independent_sources} source(s) · {node.health
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
                                            : " · not independent"} · retrieved {row.retrieved_at ??
                                            "unknown"}
                                    </footer>
                                </blockquote>
                            {/each}
                        {:else}
                            <p class="state empty">
                                No sources — this claim rests on an interval or a rule, not a
                                citation.
                            </p>
                        {/if}
                    </details>
                {/each}
            </article>
        {/if}
    {/if}
{/await}
