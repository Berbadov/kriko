<script lang="ts">
    import ClaimCard from "../lib/ClaimCard.svelte";
    import { ApiError, api } from "../lib/api";
    import { navigate } from "../lib/router";
    import type { AnalyzeResult } from "../lib/types";

    let url = $state("");
    let title = $state("");
    let description = $state("");
    let rawFields = $state("{}");
    let result = $state<AnalyzeResult | null>(null);
    let message = $state("");
    let messageState = $state("error");
    let busy = $state(false);

    const SUMMARY: Record<string, string> = {
        "no-match": "No installed pack matched this listing.",
        empty: "A subject matched, but there are no claims to show.",
        results: "Known risks for this listing.",
    };

    function outcome(data: AnalyzeResult): string {
        if (data.claims.length) return "results";
        return data.coverage === "NOT_MATCHED" ? "no-match" : "empty";
    }

    async function analyze() {
        result = null;
        message = "";
        if (!url.trim()) {
            messageState = "error";
            message = "URL is required.";
            return;
        }
        let fields: Record<string, unknown>;
        try {
            fields = JSON.parse(rawFields || "{}");
        } catch (e) {
            messageState = "error";
            message = `Fields must be a JSON object: ${(e as Error).message}`;
            return;
        }
        busy = true;
        try {
            result = await api.analyze({ url: url.trim(), title, description, fields });
            messageState = outcome(result);
            message = SUMMARY[messageState];
            // Only navigate away when there is something to read. An empty or
            // unmatched analysis is more useful beside the form that produced
            // it, where the reader can correct the input.
            if (result.lookup_id && result.claims.length) {
                navigate("result", result.lookup_id);
            }
        } catch (e) {
            messageState = e instanceof ApiError && e.status === 404 ? "unknown" : "error";
            message =
                messageState === "unknown"
                    ? "No adapter is installed for this listing."
                    : `Analysis failed: ${(e as Error).message}`;
        } finally {
            busy = false;
        }
    }
</script>

<h2>Analyze a raw listing</h2>
<p class="meta">Send the listing as captured. Pack adapters decide which fields matter.</p>

<div class="field wide">
    <label for="raw-url">URL</label>
    <input
        id="raw-url"
        type="url"
        bind:value={url}
        placeholder="https://example.invalid/item/1"
    />
</div>
<div class="field wide">
    <label for="raw-title">Title</label>
    <input id="raw-title" bind:value={title} />
</div>
<div class="field wide">
    <label for="raw-description">Description</label>
    <textarea id="raw-description" rows="3" bind:value={description}></textarea>
</div>
<div class="field wide">
    <label for="raw-fields">Raw fields (JSON object)</label>
    <textarea id="raw-fields" rows="6" bind:value={rawFields}></textarea>
</div>

<div class="row">
    <button onclick={analyze} disabled={busy}>{busy ? "Analyzing…" : "Analyze"}</button>
    <button
        class="ghost"
        onclick={() => {
            url = "";
            title = "";
            description = "";
            rawFields = "{}";
            result = null;
            message = "";
        }}>Clear</button
    >
</div>

<div aria-live="polite">
    {#if message}
        <div class="state {messageState}">
            <strong>{message}</strong>
            {#if result}<span> {result.coverage ?? "UNKNOWN"} · {result.method}</span>{/if}
        </div>
    {/if}
    {#each result?.claims ?? [] as claim}
        <ClaimCard {claim} detailed />
    {/each}
</div>
