<script lang="ts">
    import EmptyState from "./EmptyState.svelte";
    import Failure from "./Failure.svelte";
    import { api } from "./api";
    import { count } from "./plural";
    import { collect, contextLabel, humanize } from "./fields";
    import type { LookupResult, Pack, SearchHit, Subject, SubjectDetail, Term } from "./types";

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
    let matches = $state<SearchHit[]>([]);
    let searchSeq = 0;
    let searchTimer: ReturnType<typeof setTimeout> | undefined;
    let error = $state<unknown>(null);
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
    const isEmpty = $derived(
        !query && !Object.values(identity).some(Boolean) && !Object.values(context).some(Boolean),
    );

    async function loadPack() {
        const [allKinds, keys, vocabulary] = await Promise.all([
            api.kinds(),
            api.identityKeys(packId),
            api.vocabulary(packId),
        ]);
        kinds = allKinds.filter((k) => k.pack_id === packId).map((k) => k.kind);
        kind = kinds[0] ?? "";
        // The server now parses `match_json` (written as YAML) itself and
        // hands back a plain bool — the form used to `JSON.parse` it and
        // silently treat every required key as optional (check-2).
        identityKeys = keys;
        contextTerms = vocabulary.context_key ?? [];
        identity = {};
        context = {};
    }

    async function load() {
        packs = (await api.packs()).filter((p) => p.enabled);
        if (packs.length) {
            // B146: opened on whichever pack sorted first, which put a
            // one-subject pack ahead of the one holding almost every claim.
            // The pack that knows the most is the likeliest question.
            packId = packs.reduce((best, p) => ((p.claims ?? 0) > (best.claims ?? 0) ? p : best))
                .pack_id;
            await loadPack();
        }
    }

    // Debounced, and keyed by a request counter rather than a busy flag
    // (check-4): a `searching` early-return dropped any keystroke that
    // arrived mid-request and nothing re-ran the search once it finished, so
    // the list could freeze on an earlier prefix. Only the most recent
    // request may still write `matches` when it lands.
    function search() {
        clearTimeout(searchTimer);
        if (query.trim().length < 2) {
            matches = [];
            return;
        }
        const q = query.trim();
        searchTimer = setTimeout(async () => {
            const n = ++searchSeq;
            // /api/search, not /api/subjects?q= (check-5): it matches
            // aliases and identity values too, filters by pack on the
            // server rather than after the limit, and — the point of
            // switching — carries each hit's identity so two rows sharing a
            // label can be told apart, and a reachable claim count computed
            // through relations rather than a product row's own (always 0).
            const r = await api.search(q, packId, 8);
            if (n !== searchSeq) return; // a newer keystroke has already fired
            matches = r;
            activeMatch = -1;
        }, 150);
    }

    // Arrow keys stayed in the input and Enter did nothing (check-26): a
    // sighted mouse user could pick a result, a keyboard user could not.
    // `activeMatch` is which row Down/Up have moved to; -1 means none yet.
    let activeMatch = $state(-1);
    function onSearchKey(event: KeyboardEvent) {
        if (!matches.length) return;
        if (event.key === "ArrowDown") {
            event.preventDefault();
            activeMatch = (activeMatch + 1) % matches.length;
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            activeMatch = (activeMatch - 1 + matches.length) % matches.length;
        } else if (event.key === "Enter" && activeMatch >= 0) {
            event.preventDefault();
            pick(matches[activeMatch]);
        }
    }

    // Picking a known subject fills the identity keys from the store, which is
    // the whole point of searching first: the reader stops guessing spellings.
    async function pick(subject: SearchHit) {
        query = subject.label;
        matches = [];
        const detail: SubjectDetail = await api.subject(subject.subject_id);
        kind = detail.kind;
        identity = Object.fromEntries(
            detail.attributes.filter((a) => a.is_identity).map((a) => [a.key, a.value_text]),
        );
    }

    async function ask() {
        error = null;
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
            error = e;
        } finally {
            busy = false;
        }
    }

    function clear() {
        identity = {};
        context = {};
        query = "";
        matches = [];
        error = null;
        more = false;
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
                            {#each kinds as k (k)}<option value={k}>{humanize(k)}</option>{/each}
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
                onkeydown={onSearchKey}
                role="combobox"
                aria-expanded={matches.length > 0}
                aria-controls="subject-matches"
                autocomplete="off"
                placeholder="start typing…"
            />
        </div>

        {#if matches.length}
            <ul class="matches" id="subject-matches" role="listbox">
                {#each matches as match, i (match.subject_id)}
                    <li role="option" aria-selected={i === activeMatch}>
                        <button
                            class="ghost"
                            class:active={i === activeMatch}
                            onclick={() => pick(match)}
                        >
                            {match.label}
                            {#if matches.filter((m) => m.label === match.label).length > 1}
                                <span class="meta">
                                    {Object.entries(match.identity)
                                        .slice(0, 2)
                                        .map(([k, v]) => `${humanize(k)} ${v}`)
                                        .join(", ")}
                                </span>
                            {/if}
                            <span class="meta">
                                {match.kind}
                                {#if match.claims}· {count(match.claims, "known risk")}{/if}
                            </span>
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
                                {contextLabel(term.term_id, term.unit)}
                                {#if term.unit}<span class="meta">({term.unit})</span>{/if}
                            </label>
                            <input id="ctx-{term.term_id}" bind:value={context[term.term_id]} />
                        </div>
                    {/each}
                </div>
            {/if}
        {/if}

        <div class="row">
            <button class="primary" onclick={ask} disabled={busy || missing.length > 0}>
                {busy ? "Looking…" : "What goes wrong with this one?"}
            </button>
            <button class="ghost" onclick={clear} disabled={isEmpty}>Clear</button>
            {#if missing.length}
                <span class="meta">Still needed: {missing.map(humanize).join(", ")}</span>
            {/if}
        </div>

        <div aria-live="polite">
            {#if error}<Failure {error} />{/if}
        </div>
    {/if}
{:catch e}
    <Failure error={e} />
{/await}
