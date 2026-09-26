<script lang="ts">
    import Describe from "../lib/Describe.svelte";
    import Failure from "../lib/Failure.svelte";
    import Report from "../lib/Report.svelte";
    import { ApiError, api } from "../lib/api";
    import type { Mode } from "../lib/mode";
    import { navigate } from "../lib/router";
    import type { Adapter, LookupResult } from "../lib/types";

    let { mode = "buyer" }: { mode?: Mode } = $props();

    let url = $state("");
    let adapters = $state<Adapter[]>([]);
    let unreadable = $state(false);
    let pageFields = $state<{ label: string; value: string }[]>([]);
    let result = $state<LookupResult | null>(null);
    // Two different things, deliberately two variables. `hint` is a sentence
    // this app wrote about the form ("paste a link first"); `error` is an
    // exception the engine raised. They were one string, which meant the
    // reader's own typo and a dead engine rendered identically — and neither
    // could carry the remedy the other needed (B79).
    let hint = $state("");
    let error = $state<unknown>(null);
    let busy = $state(false);

    async function load() {
        adapters = await api.adapters().catch(() => [] as Adapter[]);
    }

    async function checkUrl() {
        hint = "";
        error = null;
        unreadable = false;
        result = null;
        if (!url.trim()) {
            hint = "Paste the listing's web address first.";
            return;
        }
        busy = true;
        try {
            const fields = Object.fromEntries(
                pageFields.filter((f) => f.label.trim()).map((f) => [f.label.trim(), f.value]),
            );
            const data = await api.analyze({
                url: url.trim(),
                title: "",
                description: "",
                fields,
            });
            if (data.lookup_id) navigate("result", data.lookup_id);
            else result = data;
        } catch (e) {
            // A 404 here is not an error the reader caused: it means no
            // installed pack ships an adapter for that site, which has its own
            // answer and its own next step.
            if (e instanceof ApiError && e.status === 404) unreadable = true;
            else error = e;
        } finally {
            busy = false;
        }
    }

    function onResult(data: LookupResult) {
        if (data.lookup_id) navigate("result", data.lookup_id);
        else result = data;
    }

    const ready = load();
</script>

<section class="hero">
    <h2>Check one before you buy it</h2>
    <p class="hero-sub">
        Paste a listing and Kriko reports what is known to go wrong with that exact
        one — from the packs installed on this machine, with no account, and the
        listing itself never leaves this machine.
    </p>
    <div class="field wide">
        <label for="listing-url">Paste the listing's web address</label>
        <input
            id="listing-url"
            type="url"
            bind:value={url}
            placeholder="https://…"
            onkeydown={(e) => e.key === "Enter" && checkUrl()}
        />
    </div>
    <div class="row">
        <button class="primary" onclick={checkUrl} disabled={busy}>
            {busy ? "Checking…" : "Check this listing"}
        </button>
    </div>
</section>

{#await ready then}
    {#if unreadable}
        <div class="state no-match">
            <strong>No installed pack can read that site.</strong>
            {#if adapters.length}
                <p class="meta">Readable right now:</p>
                <ul class="meta">
                    {#each adapters as adapter (adapter.id)}
                        <li>{adapter.site} — {adapter.pack_id}</li>
                    {/each}
                </ul>
            {:else}
                <p class="meta">
                    No installed pack ships a site adapter, so there is nothing to read
                    a listing with yet.
                </p>
            {/if}
            <p class="meta">Describe it by hand below instead.</p>
        </div>
    {/if}

    <div aria-live="polite">
        {#if hint}
            <p class="state no-match">{hint}</p>
        {:else if error}
            <Failure {error} />
        {:else if result}
            <Report {result} {mode} lookupId={result.lookup_id ?? ""} />
        {/if}
    </div>

    <details class="alt-path" open={unreadable}>
        <summary><h3>No link? Describe it instead</h3></summary>
        <Describe {onResult} />
    </details>

    {#if mode === "author"}
        <details class="wide">
            <summary class="meta">Page fields, as scraped (author)</summary>
            <p class="meta">
                Sent with the URL, to try an adapter's mapping against fields you paste
                by hand.
            </p>
            {#each pageFields as field, index}
                <div class="row">
                    <div class="field">
                        <label for="fl-{index}">Label</label>
                        <input id="fl-{index}" bind:value={field.label} />
                    </div>
                    <div class="field">
                        <label for="fv-{index}">Value</label>
                        <input id="fv-{index}" bind:value={field.value} />
                    </div>
                    <button
                        class="ghost"
                        onclick={() => (pageFields = pageFields.filter((_, i) => i !== index))}
                        >Remove</button
                    >
                </div>
            {/each}
            <button
                class="ghost"
                onclick={() => (pageFields = [...pageFields, { label: "", value: "" }])}
                >Add a field</button
            >
        </details>
    {/if}
{/await}
