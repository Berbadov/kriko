<script lang="ts">
    import ClaimCard from "../lib/ClaimCard.svelte";
    import { api } from "../lib/api";
    import { collect } from "../lib/fields";
    import type { LookupResult, Pack, Term } from "../lib/types";

    let packs = $state<Pack[]>([]);
    let packId = $state("");
    let kinds = $state<string[]>([]);
    let kind = $state("");
    let identityKeys = $state<string[]>([]);
    let contextTerms = $state<Term[]>([]);
    let identity = $state<Record<string, string>>({});
    let context = $state<Record<string, string>>({});
    let result = $state<LookupResult | null>(null);
    let error = $state("");
    let busy = $state(false);

    async function loadPack() {
        const [allKinds, keys, vocabulary] = await Promise.all([
            api.kinds(),
            api.identityKeys(packId),
            api.vocabulary(packId),
        ]);
        kinds = allKinds.filter((k) => k.pack_id === packId).map((k) => k.kind);
        kind = kinds[0] ?? "";
        identityKeys = keys.map((k) => k.key);
        contextTerms = vocabulary.context_key ?? [];
        identity = {};
        context = {};
    }

    async function loadPacks() {
        packs = (await api.packs()).filter((p) => p.enabled);
        if (packs.length) {
            packId = packs[0].pack_id;
            await loadPack();
        }
    }

    async function ask() {
        busy = true;
        error = "";
        result = null;
        try {
            result = await api.lookup({
                kind,
                identity: collect(identity),
                context: collect(context),
            });
        } catch (e) {
            error = (e as Error).message;
        } finally {
            busy = false;
        }
    }

    const ready = loadPacks();
</script>

<h2>Ask the installed knowledge</h2>

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if !packs.length}
        <p class="state empty">No packs installed.</p>
    {:else}
        <div class="row">
            <div class="field">
                <label for="pack">Pack</label>
                <select id="pack" bind:value={packId} onchange={loadPack}>
                    {#each packs as pack}<option value={pack.pack_id}>{pack.name}</option
                        >{/each}
                </select>
            </div>
            <div class="field">
                <label for="kind">Kind</label>
                <select id="kind" bind:value={kind}>
                    {#each kinds as k}<option value={k}>{k}</option>{/each}
                </select>
            </div>
        </div>

        <div class="row">
            {#each identityKeys as key (key)}
                <div class="field">
                    <label for="id-{key}">{key}</label>
                    <input id="id-{key}" bind:value={identity[key]} />
                </div>
            {/each}
        </div>

        <div class="row">
            {#each contextTerms as term (term.term_id)}
                <div class="field">
                    <label for="ctx-{term.term_id}">
                        {term.term_id} <span class="meta">{term.unit}</span>
                    </label>
                    <input id="ctx-{term.term_id}" bind:value={context[term.term_id]} />
                </div>
            {/each}
        </div>

        <div class="row">
            <button onclick={ask} disabled={busy}>{busy ? "Looking up…" : "Ask"}</button>
            <button
                class="ghost"
                onclick={() => {
                    identity = {};
                    context = {};
                    result = null;
                    error = "";
                }}>Clear</button
            >
        </div>

        <div aria-live="polite">
            {#if error}
                <p class="state error">{error}</p>
            {:else if result}
                {#if result.claims.length}
                    {#each result.claims as claim}<ClaimCard {claim} detailed />{/each}
                {:else}
                    <p class="state {result.method === 'no_match' ? 'no-match' : 'empty'}">
                        {result.method === "no_match"
                            ? "No matching subject."
                            : "No claims found."}
                    </p>
                {/if}
            {/if}
        </div>
    {/if}
{:catch e}
    <p class="state error">Could not load this view: {e.message}</p>
{/await}
