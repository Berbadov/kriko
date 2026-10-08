<script lang="ts">
    import JackMark from "./kriko/JackMark.svelte";
    import { api } from "./api";
    import { ApiError } from "./api";
    import { remedyFor } from "./failure";
    import { groundingTone, groundingWord } from "./report";
    import type { GroundingEvidence } from "./types";

    let { packId, claimId }: { packId: string; claimId: string } = $props();

    type Load = "idle" | "loading" | "loaded" | "error";
    let load = $state<Load>("idle");
    let evidence = $state<GroundingEvidence[]>([]);
    let loadError = $state("");

    type DocState = "loading" | "error" | "not-kept" | { text: string; url: string };
    let docs = $state<Record<string, DocState>>({});

    /** The narrow helper the template needs: a plain `typeof` check does not
     *  survive across separate `{...}` expressions in Svelte markup the way
     *  it would inside one TypeScript function body. */
    function loadedDoc(sourceId: string): { text: string; url: string } | undefined {
        const doc = docs[sourceId];
        return typeof doc === "object" ? doc : undefined;
    }

    async function open(event: Event) {
        if (!(event.currentTarget as HTMLDetailsElement).open) return;
        if (load !== "idle") return;
        load = "loading";
        try {
            const result = await api.grounding(packId, claimId);
            evidence = result.evidence;
            load = "loaded";
        } catch (cause) {
            loadError = remedyFor(cause).headline;
            load = "error";
        }
    }

    async function toggleDocument(sourceId: string) {
        if (docs[sourceId] !== undefined) {
            const { [sourceId]: _drop, ...rest } = docs;
            docs = rest;
            return;
        }
        docs = { ...docs, [sourceId]: "loading" };
        try {
            const doc = await api.document(sourceId);
            docs = { ...docs, [sourceId]: { text: doc.text, url: doc.url } };
        } catch (cause) {
            const notKept = cause instanceof ApiError && cause.status === 404;
            docs = { ...docs, [sourceId]: notKept ? "not-kept" : "error" };
        }
    }
</script>

<!-- Grounding is asked offline, against what this install already read — a
     different question from "Check the source" above, which fetches the page
     again. Lazy behind a disclosure: it is provenance for the reader who
     wants it, not a request this card fires for every claim on a report of
     forty. -->
<details ontoggle={open}>
    <summary class="meta">Retained pages · what was actually kept</summary>
    {#if load === "loading"}
        <p class="meta loading-mark"><JackMark />Checking what was kept…</p>
    {:else if load === "error"}
        <p class="meta">{loadError}</p>
    {:else if load === "loaded"}
        {#if evidence.length === 0}
            <p class="meta">No evidence recorded for this claim.</p>
        {:else}
            <ul class="grounding-list">
                {#each evidence as row (row.evidence_id)}
                    <li>
                        <span class="badge fact-{groundingTone(row.verdict)}"
                            >{groundingWord(row.verdict)}</span
                        >
                        <blockquote>{row.quote}</blockquote>
                        {#if row.verdict !== "not_kept"}
                            <button
                                type="button"
                                class="link-ish"
                                onclick={() => toggleDocument(row.source_id)}
                            >
                                {loadedDoc(row.source_id)
                                    ? "Hide the retained page"
                                    : "View the retained page"}
                            </button>
                        {/if}
                        {#if docs[row.source_id] === "loading"}
                            <p class="meta loading-mark"><JackMark />Loading the retained page…</p>
                        {:else if docs[row.source_id] === "not-kept"}
                            <p class="meta">No page was kept for this source.</p>
                        {:else if docs[row.source_id] === "error"}
                            <p class="meta">Could not load the retained page.</p>
                        {:else if loadedDoc(row.source_id)}
                            <div class="log">{loadedDoc(row.source_id)?.text}</div>
                            <p class="meta">
                                <a
                                    href={loadedDoc(row.source_id)?.url}
                                    target="_blank"
                                    rel="noreferrer">{loadedDoc(row.source_id)?.url}</a
                                >
                            </p>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}
    {/if}
</details>

<style>
    .grounding-list {
        list-style: none;
        margin: var(--s-2) 0 0;
        padding: 0;
        display: grid;
        gap: var(--s-3);
    }
    .grounding-list li {
        display: grid;
        gap: var(--s-1);
    }
</style>
