<script lang="ts">
    import type { Mode } from "./mode";
    import Grounding from "./Grounding.svelte";
    import {
        askLine,
        canCheckFacts,
        factTone,
        factWord,
        rankingNote,
        severityWord,
        sourceSummary,
    } from "./report";
    import type { Claim, FactCheck } from "./types";

    let {
        claim,
        mode = "buyer",
        checked = false,
        note = "",
        onCheck,
        onNote,
        factCheck = null,
        checkingFacts = false,
        onCheckFacts,
    }: {
        claim: Claim;
        mode?: Mode;
        checked?: boolean;
        note?: string;
        onCheck?: (checked: boolean) => void;
        onNote?: (note: string) => void;
        factCheck?: FactCheck | null;
        checkingFacts?: boolean;
        onCheckFacts?: () => void;
    } = $props();

    // Offered on the card rather than only in the sources fold: "is this
    // still true" is the question a reader has *while reading the claim*, and
    // a button behind a disclosure triangle is a button they never find.
    const checkable = $derived(Boolean(onCheckFacts) && canCheckFacts(claim));

    const author = $derived(mode === "author");

    // The field opens when there is something in it, and stays open once the
    // reader has opened it. A textarea under every card by default turns a
    // report into a form; one behind a link that remembers its own state is
    // the same feature without the wall of boxes.
    let noteOpen = $state(false);
    const showNote = $derived(noteOpen || Boolean(note));

    // Saved on blur rather than per keystroke: this is one row in SQLite and a
    // request per character would be a write storm for no gain. The parent
    // paints optimistically either way.
    let draft = $state("");
    // Initialised in an effect rather than from the prop directly: `$state(note)`
    // captures only the first value, so a card whose note arrives with the
    // triage fetch (a beat after mount) would render an empty box over a
    // stored sentence.
    $effect(() => {
        draft = note;
    });
</script>

<article class="card risk" class:done={checked}>
    <header class="risk-head">
        <span class="sev {claim.severity}">{severityWord(claim.severity)}</span>
        <h3>{claim.title}</h3>
        <!-- Out of the provenance fold and out of author mode. A disputed
             claim is exactly the one whose dispute the reader needs to see:
             folded twice, it reached nobody who was not already auditing. -->
        {#if claim.disputed}
            <span class="badge disputed" title="A source disagrees with this claim"
                >disputed</span
            >
        {/if}
        {#if onCheck}
            <label class="check">
                <input
                    type="checkbox"
                    {checked}
                    onchange={(event) => onCheck(event.currentTarget.checked)}
                />
                Handled
            </label>
        {/if}
    </header>

    <p>{claim.body}</p>

    <p class="ask"><strong>What to ask:</strong> {askLine(claim)}</p>

    {#if onNote}
        {#if showNote}
            <label class="note-field">
                <span class="meta">What the seller said</span>
                <textarea
                    rows="2"
                    bind:value={draft}
                    placeholder="e.g. done at 140,000 — receipt promised"
                    onblur={() => draft !== note && onNote(draft)}
                ></textarea>
            </label>
        {:else}
            <button type="button" class="link-ish" onclick={() => (noteOpen = true)}>
                Add what the seller said
            </button>
        {/if}
    {/if}

    <p class="meta">{claim.subject} · {sourceSummary(claim)}</p>

    {#if checkable || factCheck}
        <p class="fact no-print">
            {#if factCheck}
                <span class="badge fact-{factTone(factCheck.verdict)}"
                    >{factWord(factCheck.verdict)}</span
                >
                <!-- The date, always. A re-check is an observation with a
                     time on it, and "source still says this" with no when is
                     the kind of reassurance that ages badly. -->
                <span class="meta">checked {factCheck.checked_at.slice(0, 10)}</span>
                {#if factCheck.detail}<span class="meta">{factCheck.detail}</span>{/if}
            {/if}
            {#if checkable}
                <button type="button" class="link-ish" disabled={checkingFacts}
                    onclick={onCheckFacts}
                >
                    {checkingFacts
                        ? "Reading the source…"
                        : factCheck
                          ? "Check again"
                          : "Check the source"}
                </button>
            {/if}
        </p>
    {/if}

    {#if author}
        <details class="provenance">
            <summary class="meta">Why this ranked here</summary>
            <!-- The numbers, but said in words first. A bare 0.72 is not
                 auditable by anyone who does not already know the scale. -->
            <p class="meta">{rankingNote(claim)}</p>
            <!-- And then the raw values, because an author auditing a rank
                 needs the number they can compare against another claim's. -->
            <p class="meta">
                relevance {claim.relevance}{claim.trust !== undefined
                    ? ` · trust ${claim.trust}`
                    : ""} · {claim.pack_id}
            </p>
            {#if claim.why?.length}
                <ul class="why">
                    {#each claim.why as reason}<li>{reason}</li>{/each}
                </ul>
            {/if}
        </details>
    {/if}

    {#if claim.sources?.length}
        <details>
            <summary class="meta">
                {author
                    ? `${claim.sources.length} source(s)`
                    : `Where this comes from — ${sourceSummary(claim)}`}
            </summary>
            {#each claim.sources as source}
                <blockquote class={source.stance === "refutes" ? "refutes" : ""}>
                    {source.quote}
                    <footer class="meta">
                        {#if author}
                            {source.domain} · {source.tier} · {source.stance}
                        {:else}
                            {source.domain}{source.stance === "refutes"
                                ? " — disagrees"
                                : ""}
                        {/if}
                    </footer>
                </blockquote>
            {/each}
        </details>
    {/if}

    {#if claim.claim_id}
        <Grounding packId={claim.pack_id} claimId={claim.claim_id} />
    {/if}
</article>
