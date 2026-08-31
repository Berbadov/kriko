<script lang="ts">
    import type { Claim } from "./types";

    let { claim, detailed = false }: { claim: Claim; detailed?: boolean } = $props();
</script>

<article class="card">
    <h3>
        {#if claim.severity}<span class="sev {claim.severity}">{claim.severity}</span>{/if}
        {claim.title}
    </h3>
    <p>{claim.body}</p>
    {#if claim.advice}<p class="advice">{claim.advice}</p>{/if}
    <p class="meta">
        {claim.subject} · {claim.pack_id}{#if detailed} · relevance {claim.relevance}{/if}
    </p>
    {#if detailed && claim.why?.length}
        <ul class="meta">
            {#each claim.why as reason}<li>{reason}</li>{/each}
        </ul>
    {/if}
    {#if claim.sources?.length}
        <details>
            <summary class="meta">{claim.sources.length} source(s)</summary>
            {#each claim.sources as source}
                <blockquote class={source.stance === "refutes" ? "refutes" : ""}>
                    {source.quote}
                    <footer class="meta">
                        {source.domain} · {source.tier} · {source.stance}
                    </footer>
                </blockquote>
            {/each}
        </details>
    {/if}
</article>
