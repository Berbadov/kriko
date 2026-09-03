<script lang="ts">
    import EmptyState from "./EmptyState.svelte";
    import { api } from "./api";
    import { collect, humanize } from "./fields";
    import type { LookupResult, Pack, Subject, SubjectDetail, Term } from "./types";

    let { onResult }: { onResult: (result: LookupResult) => void } = $props();

    let packs = $state<Pack[]>([]);
    let packId = $state("");
    let kinds = $state<string[]>([]);
    let kind = $state("");
    let identityKeys = $state<{ key: string; required: boolean }[]>([]);
    let contextTerms = $state<Term[]>([]);
    let identity = $state<Record<string, string>>({});
    let context = $state<Record<string, string>>({});

    let query = $state("");
    let matches = $state<Subject[]>([]);
    let searching = false;
    let error = $state("");
    let busy = $state(false);
    let more = $state(false);

    // A choice with one option is not a choice; asking it is a step the reader
    // pays for and learns nothing from.
    const choosePack = $derived(packs.length > 1);
    const chooseKind = $derived(kinds.length > 1);

    const requiredKeys = $derived(identityKeys.filter((k) => k.required));
    const optionalKeys = $derived(identityKeys.filter((k) => !k.required));
    const missing = $derived(
        requiredKeys.filter((k) => !(identity[k.key] ?? "").trim()).map((k) => k.key),
    );

    function required(key: { key: string; match_json?: string }): boolean {
        // The pack declares which attributes select a subject; the form reads
        // that rather than deciding for itself which fields matter.
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
        packs = (await api.packs()).filter((p) => p.enabled);
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

    // Picking a known subject fills the identity keys from the store, which is
    // the whole point of searching first: the reader stops guessing spellings.
    async function pick(subject: Subject) {
        query = subject.label;
        matches = [];
        const detail: SubjectDetail = await api.subject(subject.subject_id!);
        kind = detail.kind;
        identity = Object.fromEntries(
            detail.attributes.filter((a) => a.is_identity).map((a) => [a.key, a.value_text]),
        );
    }

    async function ask() {
        error = "";
        if (missing.length) return;
        busy = true;
        try {
            onResult(
                await api.lookup({
                    kind,
                    identity: collect(identity),
                    context: collect(context),
                }),
            );
        } catch (e) {
            error = e instanceof Error ? e.message : String(e);
        } finally {
            busy = false;
        }
    }

    function clear() {
        identity = {};
        context = {};
        query = "";
        matches = [];
        error = "";
    }

    const ready = load();
</script>

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if !packs.length}
        <EmptyState
            title="No packs installed, so there is nothing to ask"
            detail="The engine answers from installed knowledge. Install a pack and this
                    form fills itself in from what that pack declares."
        />
    {:else}
        {#if choosePack || chooseKind}
            <div class="row">
                {#if choosePack}
                    <div class="field">
                        <label for="pack">Pack</label>
                        <select id="pack" bind:value={packId} onchange={loadPack}>
                            {#each packs as pack (pack.pack_id)}
                                <option value={pack.pack_id}>{pack.name}</option>
                            {/each}
                        </select>
                    </div>
                {/if}
                {#if chooseKind}
                    <div class="field">
                        <label for="kind">Kind</label>
                        <select id="kind" bind:value={kind}>
                            {#each kinds as k (k)}<option value={k}>{k}</option>{/each}
                        </select>
                    </div>
                {/if}
            </div>
        {/if}

        <div class="field wide">
            <label for="subject-search">Find one the pack already knows</label>
            <input
                id="subject-search"
                bind:value={query}
                oninput={search}
                autocomplete="off"
                placeholder="start typing…"
            />
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
            {#each requiredKeys as key (key.key)}
                <div class="field">
                    <label for="id-{key.key}">
                        {humanize(key.key)}<span class="req">*</span>
                    </label>
                    <input id="id-{key.key}" bind:value={identity[key.key]} />
                </div>
            {/each}
        </div>

        {#if optionalKeys.length || contextTerms.length}
            <!-- A button and an {#if}, not a <details>: the optional inputs are
                 form controls, and one that is present-but-hidden still submits,
                 still takes focus on Tab, and still counts as filled in. Closing
                 this disclosure should mean "I am not answering these". -->
            <button
                class="ghost disclose"
                aria-expanded={more}
                onclick={() => (more = !more)}
            >
                {more ? "Fewer details" : "More details — narrows the answer"}
            </button>
            {#if more}
                <div class="row">
                    {#each optionalKeys as key (key.key)}
                        <div class="field">
                            <label for="id-{key.key}">{humanize(key.key)}</label>
                            <input id="id-{key.key}" bind:value={identity[key.key]} />
                        </div>
                    {/each}
                </div>
                <div class="row">
                    {#each contextTerms as term (term.term_id)}
                        <div class="field">
                            <label for="ctx-{term.term_id}">
                                {humanize(term.term_id)}
                                <span class="meta">{term.unit}</span>
                            </label>
                            <input id="ctx-{term.term_id}" bind:value={context[term.term_id]} />
                        </div>
                    {/each}
                </div>
            {/if}
        {/if}

        <div class="row">
            <button onclick={ask} disabled={busy || missing.length > 0}>
                {busy ? "Looking…" : "What goes wrong with this one?"}
            </button>
            <button class="ghost" onclick={clear}>Clear</button>
            {#if missing.length}
                <span class="meta">Still needed: {missing.map(humanize).join(", ")}</span>
            {/if}
        </div>

        <div aria-live="polite">
            {#if error}<p class="state error">{error}</p>{/if}
        </div>
    {/if}
{:catch e}
    <p class="state error">Could not load this view: {e.message}</p>
{/await}
