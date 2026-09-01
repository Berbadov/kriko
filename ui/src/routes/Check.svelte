<script lang="ts">
    import Report from "../lib/Report.svelte";
    import { ApiError, api } from "../lib/api";
    import { collect } from "../lib/fields";
    import type { Mode } from "../lib/mode";
    import { navigate } from "../lib/router";
    import type {
        Adapter,
        LookupResult,
        Pack,
        Subject,
        SubjectDetail,
        Term,
    } from "../lib/types";

    let { mode = "buyer" }: { mode?: Mode } = $props();

    // ── the URL path ─────────────────────────────────────────────────────
    let url = $state("");
    let adapters = $state<Adapter[]>([]);
    let unreadable = $state(false);

    // ── the guided path ──────────────────────────────────────────────────
    let packs = $state<Pack[]>([]);
    let packId = $state("");
    let kinds = $state<string[]>([]);
    let kind = $state("");
    let identityKeys = $state<{ key: string; required: boolean }[]>([]);
    let contextTerms = $state<Term[]>([]);
    let identity = $state<Record<string, string>>({});
    let context = $state<Record<string, string>>({});

    // ── author-only extras ───────────────────────────────────────────────
    let pageFields = $state<{ label: string; value: string }[]>([]);

    // ── shared ───────────────────────────────────────────────────────────
    let result = $state<LookupResult | null>(null);
    let error = $state("");
    let busy = $state(false);

    // Autocomplete against what is actually installed, so the reader is
    // choosing a subject the packs know rather than guessing at spellings.
    let query = $state("");
    let matches = $state<Subject[]>([]);
    let searching = false;

    const missing = $derived(
        identityKeys
            .filter((k) => k.required && !(identity[k.key] ?? "").trim())
            .map((k) => k.key),
    );

    function required(key: { key: string; match_json?: string }): boolean {
        // The pack declares which attributes actually select a subject; the
        // form reads that rather than deciding for itself which fields matter.
        try {
            return Boolean(JSON.parse(key.match_json || "{}").required);
        } catch {
            return false;
        }
    }

    async function loadPack() {
        const [allKinds, keys, vocabulary] = await Promise.all([
            api.kinds(),
            api.identityKeys(packId),
            api.vocabulary(packId),
        ]);
        kinds = allKinds.filter((k) => k.pack_id === packId).map((k) => k.kind);
        kind = kinds[0] ?? "";
        identityKeys = keys.map((k) => ({ key: k.key, required: required(k) }));
        contextTerms = vocabulary.context_key ?? [];
        identity = {};
        context = {};
    }

    async function load() {
        const [installed, sites] = await Promise.all([
            api.packs(),
            api.adapters().catch(() => [] as Adapter[]),
        ]);
        adapters = sites;
        packs = installed.filter((p) => p.enabled);
        if (packs.length) {
            packId = packs[0].pack_id;
            await loadPack();
        }
    }

    async function search() {
        if (searching || query.trim().length < 2) {
            matches = [];
            return;
        }
        searching = true;
        try {
            matches = (await api.subjects(query.trim(), 8)).filter(
                (s) => s.pack_id === packId,
            );
        } finally {
            searching = false;
        }
    }

    async function pick(subject: Subject) {
        query = subject.label;
        matches = [];
        const detail: SubjectDetail = await api.subject(subject.subject_id!);
        kind = detail.kind;
        identity = Object.fromEntries(
            detail.attributes
                .filter((a) => a.is_identity)
                .map((a) => [a.key, a.value_text]),
        );
    }

    function fail(e: unknown) {
        error = e instanceof Error ? e.message : String(e);
    }

    async function checkUrl() {
        error = "";
        unreadable = false;
        result = null;
        if (!url.trim()) {
            error = "Paste the listing's web address first.";
            return;
        }
        busy = true;
        try {
            const fields = Object.fromEntries(
                pageFields
                    .filter((f) => f.label.trim())
                    .map((f) => [f.label.trim(), f.value]),
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
            if (e instanceof ApiError && e.status === 404) unreadable = true;
            else fail(e);
        } finally {
            busy = false;
        }
    }

    async function ask() {
        error = "";
        unreadable = false;
        result = null;
        if (missing.length) {
            error = `Still needed: ${missing.join(", ")}.`;
            return;
        }
        busy = true;
        try {
            const data = await api.lookup({
                kind,
                identity: collect(identity),
                context: collect(context),
            });
            if (data.lookup_id) navigate("result", data.lookup_id);
            else result = data;
        } catch (e) {
            fail(e);
        } finally {
            busy = false;
        }
    }

    const ready = load();
</script>

<h2>Check one before you buy it</h2>

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
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
        <button onclick={checkUrl} disabled={busy}>
            {busy ? "Checking…" : "Check this listing"}
        </button>
    </div>

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
                    No installed pack ships a site adapter, so there is nothing to
                    read a listing with yet.
                </p>
            {/if}
            <p class="meta">Describe it by hand below instead.</p>
        </div>
    {/if}

    {#if mode === "author"}
        <details class="wide">
            <summary class="meta">Page fields, as scraped (author)</summary>
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
                        onclick={() =>
                            (pageFields = pageFields.filter((_, i) => i !== index))}
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

    <hr />

    {#if !packs.length}
        <p class="state empty">No packs installed, so there is nothing to ask.</p>
    {:else}
        <h3>No link? Describe it instead</h3>

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
            <div class="field grow">
                <label for="subject-search">Find one the pack already knows</label>
                <input
                    id="subject-search"
                    bind:value={query}
                    oninput={search}
                    autocomplete="off"
                    placeholder="start typing…"
                />
            </div>
        </div>

        {#if matches.length}
            <ul class="matches">
                {#each matches as match (match.subject_id)}
                    <li>
                        <button class="ghost" onclick={() => pick(match)}>
                            {match.label}
                            <span class="meta">{match.kind} · {match.claims} claim(s)</span>
                        </button>
                    </li>
                {/each}
            </ul>
        {/if}

        <div class="row">
            {#each identityKeys as key (key.key)}
                <div class="field">
                    <label for="id-{key.key}">
                        {key.key}{#if key.required}<span class="req">*</span>{/if}
                    </label>
                    <input id="id-{key.key}" bind:value={identity[key.key]} />
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
            <button onclick={ask} disabled={busy || missing.length > 0}>
                {busy ? "Looking…" : "What goes wrong with this one?"}
            </button>
            <button
                class="ghost"
                onclick={() => {
                    identity = {};
                    context = {};
                    query = "";
                    matches = [];
                    result = null;
                    error = "";
                }}>Clear</button
            >
            {#if missing.length}
                <span class="meta">Still needed: {missing.join(", ")}</span>
            {/if}
        </div>
    {/if}

    <div aria-live="polite">
        {#if error}
            <p class="state error">{error}</p>
        {:else if result}
            <Report {result} {mode} lookupId={result.lookup_id ?? ""} />
        {/if}
    </div>
{:catch e}
    <p class="state error">Could not load this view: {e.message}</p>
{/await}
