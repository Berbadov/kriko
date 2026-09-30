<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import Describe from "../lib/Describe.svelte";
    import Failure from "../lib/Failure.svelte";
    import Report from "../lib/Report.svelte";
    import { api } from "../lib/api";
    import type { Mode } from "../lib/mode";
    import { navigate } from "../lib/router";
    import type { LookupResult, Pack } from "../lib/types";

    let { mode = "buyer" }: { mode?: Mode } = $props();

    let url = $state("");
    let packTitles = $state<Record<string, string>>({});
    let readableSites = $state<{ site: string; pack_id: string }[]>([]);
    let unreadable = $state(false);
    // Distinct from `unreadable` too: the box holds text that is not a web
    // address at all, so "no installed pack can read that site" is the
    // wrong sentence — there is no site to read (check-21).
    let notAUrl = $state(false);
    // Distinct from `unreadable`: the site *is* covered, but a pasted URL
    // has no page for the adapter to read (check-1). Conflating the two
    // told the reader "no pack covers this kind of product at all", which is
    // false and worse than saying nothing.
    let notRead = $state(false);
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
        const packs = await api.packs().catch(() => [] as Pack[]);
        packTitles = Object.fromEntries(packs.map((p) => [p.pack_id, p.name || p.pack_id]));
    }

    async function checkUrl() {
        hint = "";
        error = null;
        unreadable = false;
        notRead = false;
        notAUrl = false;
        result = null;
        if (busy) return;
        const trimmed = url.trim();
        if (!trimmed) {
            hint = "Paste the listing's web address first.";
            return;
        }
        // Validated before the request, not after a 404 (check-21): "not a
        // url" and "a url nothing reads" are different problems with
        // different remedies, and this app knows which one it is without
        // asking the server.
        try {
            new URL(trimmed);
        } catch {
            notAUrl = true;
            return;
        }
        busy = true;
        try {
            const fields = Object.fromEntries(
                pageFields.filter((f) => f.label.trim()).map((f) => [f.label.trim(), f.value]),
            );
            const data = await api.analyze({
                url: trimmed,
                title: "",
                description: "",
                fields,
            });
            if (data.readable === false) {
                if (data.reason === "no_adapter") {
                    unreadable = true;
                    readableSites = data.readable_sites ?? [];
                } else {
                    notRead = true;
                }
            } else if (data.lookup_id) navigate("result", data.lookup_id);
            else result = data as LookupResult;
        } catch (e) {
            error = e;
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
    <h2><Icon name="check" size={22} /> Check one before you buy it</h2>
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
    {#if notRead}
        <div class="state no-match">
            <strong>Kriko cannot open listing pages by itself.</strong>
            <p class="meta">
                Open this ad in your browser with the extension installed, or describe
                it by hand below.
            </p>
        </div>
    {/if}

    {#if unreadable}
        <div class="state no-match">
            <strong>No installed pack can read that site.</strong>
            {#if readableSites.length}
                <p class="meta">Readable right now:</p>
                <ul class="meta">
                    {#each readableSites as site (site.site)}
                        <li>{site.site} — {packTitles[site.pack_id] ?? site.pack_id}</li>
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
        {:else if notAUrl}
            <p class="state no-match">That is not a web address.</p>
        {:else if error}
            <Failure {error} />
        {:else if result}
            <Report {result} {mode} lookupId={result.lookup_id ?? ""} />
        {/if}
    </div>

    <details class="alt-path" open={unreadable || notRead}>
        <summary><h3><Icon name="edit" /> No link? Describe it instead</h3></summary>
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
