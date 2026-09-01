<script lang="ts">
    import type { Mode } from "./mode";
    import { askLine, severityWord, sourceSummary } from "./report";
    import type { Claim } from "./types";

    let {
        claim,
        mode = "buyer",
        checked = false,
        onCheck,
    }: {
        claim: Claim;
        mode?: Mode;
        checked?: boolean;
        onCheck?: (checked: boolean) => void;
    } = $props();

    const author = $derived(mode === "author");
</script>

<article class="card risk" class:done={checked}>
    <header class="risk-head">
        <span class="sev {claim.severity}">{severityWord(claim.severity)}</span>
        <h3>{claim.title}</h3>
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

    {#if author}
        <p class="meta">
            {claim.subject} · {claim.pack_id} · relevance {claim.relevance}
            {#if claim.detection} · detection {claim.detection}{/if}
            {#if claim.disputed}<span class="badge disputed">disputed</span>{/if}
        </p>
        {#if claim.why?.length}
            <ul class="why">
                {#each claim.why as reason}<li>{reason}</li>{/each}
            </ul>
        {/if}
    {:else}
        <p class="meta">{claim.subject} · {sourceSummary(claim)}</p>
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
</article>
