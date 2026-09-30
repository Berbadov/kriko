<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { stamp } from "../lib/time";
    import type { Submission } from "../lib/types";

    /* What a researcher sent, and what the gate did with it.
     *
     * `app/findings.py` refuses most of what arrives, and each refusal names
     * the rule it broke — a quote that is not in the cited document, a title
     * tied to nothing specific, an item the pack's own principle calls
     * routine. Those sentences are the best feedback this project gets about
     * the research skill, and until now they existed only in a return value
     * nobody could read: an agent submitted twenty findings, three landed, and
     * the seventeen were unexplained on both sides of the wire.
     *
     * Deliberately not a review queue. Nothing here is pending, nothing waits
     * on the reader, and there is no button to accept something the gate
     * refused — the automation principle says no human stands in the data
     * path. It is a *record*, read to change the skill or the gate.
     */

    const load = () => api.submissions(50);
    let promise = $state(load());

    let open = $state<string | null>(null);

    const rate = (accepted: number, refused: number) =>
        accepted + refused ? Math.round((100 * accepted) / (accepted + refused)) : 0;

    const rejected = (item: Submission) => item.verdicts.rejected ?? [];
    const accepted = (item: Submission) => item.verdicts.accepted ?? [];
</script>

<h2><Icon name="submissions" size={22} /> Submissions</h2>
<p class="lede">
    Every batch that reached the gate, and the reason each finding was turned away.
    Nothing here is waiting for you — the decisions were made when the batch
    arrived. Read it to fix the gate or the skill, not to sign anything off.
</p>

<Async {promise} loading="Reading the ledger…">
    {#snippet children(data)}
        {#if !data.items.length}
            <EmptyState
                title="No batches yet"
                detail="Findings arrive through the agent door (an MCP client) or from a
                        research job started on the Knowledge screen. Both go through the
                        same gate, so both land here."
                actionLabel="Connect an agent"
                actionHref="#/connect"
            />
        {:else}
            <!-- The rate first. A list of batches says how busy the door has
                 been; the proportion says whether the skill is any good, and
                 that is the number worth changing. -->
            <ul class="strip" aria-label="What the gate did">
                <li><strong>{data.accepted}</strong> <span class="meta">accepted</span></li>
                <li class={data.refused ? "warn" : ""}>
                    <strong>{data.refused}</strong> <span class="meta">refused</span>
                </li>
                <li>
                    <strong>{rate(data.accepted, data.refused)}%</strong>
                    <span class="meta">got through</span>
                </li>
            </ul>

            {#if data.reasons.length}
                <section class="reasons">
                    <h3><Icon name="warn" /> Why findings are refused</h3>
                    <p class="meta">
                        Grouped by rule rather than by batch: one rule failing a hundred
                        times is a skill to rewrite, and a hundred one-off reasons is not.
                    </p>
                    <ul class="klist">
                        {#each data.reasons as reason (reason.reason)}
                            <li class="krow">
                                <div class="kmain">
                                    <span class="klabel">{reason.reason}</span>
                                </div>
                                <span class="meta">{reason.count}</span>
                            </li>
                        {/each}
                    </ul>
                </section>
            {/if}

            {#if (data.shapes ?? []).length}
                <section class="reasons">
                    <h3><Icon name="search" /> What was actually searched for</h3>
                    <p class="meta">
                        The pack ships seeds, not a script — an agent adapts them to the
                        subject and the market. These are the searches that came back, and
                        what each one's batches kept. A shape that keeps nothing is a seed
                        worth rewriting.
                    </p>
                    <ul class="klist">
                        {#each (data.shapes ?? []).slice(0, 12) as shape (shape.query)}
                            <li class="krow">
                                <div class="kmain">
                                    <span class="klabel">{shape.query}</span>
                                </div>
                                <span class="meta"
                                    >{shape.accepted} kept · {shape.refused} refused ·
                                    {shape.batches} batch{shape.batches === 1 ? "" : "es"}</span
                                >
                            </li>
                        {/each}
                    </ul>
                </section>
            {/if}

            <section class="batches">
                <h3><Icon name="submissions" /> Batches</h3>
                {#each data.items as item (item.submission_id)}
                    <article class="card">
                        <h4>
                            {item.subject_id || "no subject named"}
                            <span class="meta">{item.pack_id}</span>
                            <!-- Which door: an MCP client and a research job
                                 go through the same gate on purpose, and a
                                 refusal that only ever happens on one of them
                                 is a fact about that door. -->
                            <span class="badge">{item.door}</span>
                        </h4>
                        <p class="meta">
                            {stamp(item.created_at)} ·
                            {item.accepted} accepted · {item.refused} refused
                        </p>
                        {#if item.queries?.length}
                            <p class="meta">
                                searched: {item.queries.slice(0, 4).join(" · ")}
                            </p>
                        {/if}
                        {#if item.verdicts.error}
                            <p class="state error">{item.verdicts.error}</p>
                        {/if}
                        <p class="row">
                            <button
                                onclick={() =>
                                    (open = open === item.submission_id
                                        ? null
                                        : item.submission_id)}
                                aria-expanded={open === item.submission_id}
                                >Findings</button
                            >
                        </p>
                        {#if open === item.submission_id}
                            <div class="verdicts">
                                {#if rejected(item).length}
                                    <h5>Turned away</h5>
                                    <ul>
                                        {#each rejected(item) as bad, i (i)}
                                            <li>
                                                <span class="klabel">{bad.title}</span>
                                                <span class="meta">{bad.reason}</span>
                                            </li>
                                        {/each}
                                    </ul>
                                {/if}
                                {#if accepted(item).length}
                                    <h5>Kept</h5>
                                    <ul>
                                        {#each accepted(item) as good, i (i)}
                                            <li>
                                                <span class="klabel">{good.title}</span>
                                                <span class="meta">{good.claim_id}</span>
                                            </li>
                                        {/each}
                                    </ul>
                                {/if}
                                {#if !rejected(item).length && !accepted(item).length}
                                    <p class="meta">
                                        The batch recorded no per-finding verdicts.
                                    </p>
                                {/if}
                            </div>
                        {/if}
                    </article>
                {/each}
            </section>
        {/if}
    {/snippet}
</Async>

<style>
    .reasons,
    .batches {
        margin-block: var(--s-5);
    }
    .reasons > .meta {
        max-width: var(--measure);
        margin-block-end: var(--s-3);
    }
    .verdicts ul {
        list-style: none;
        padding: 0;
    }
    .verdicts li {
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
        padding-block: var(--s-2);
        border-block-end: 1px solid var(--line);
    }
    .verdicts h5 {
        margin-block: var(--s-3) var(--s-1);
    }
</style>
