<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import Failure from "../lib/Failure.svelte";
    import { remedyFor } from "../lib/failure";
    import Brief from "../lib/Brief.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import PacksSection from "../lib/PacksSection.svelte";
    import Health from "./Health.svelte";
    import { api } from "../lib/api";
    import { count } from "../lib/plural";
    import { severityWord } from "../lib/report";
    import { route } from "../lib/router";
    import type {

        Gap,
        Pack,
        PackDraft,
        Status,
        Subject,
        SubjectDetail,
        SubjectFilter,
    } from "../lib/types";
    import PageHead from "../lib/kriko/PageHead.svelte";

    /* One screen for "what does this install actually know".
     *
     * It replaces three — Subjects, Coverage, Health — which was the wrong
     * split. Those are not three places, they are three *questions about the
     * same list*: what is here, what is missing, and what is thinly supported.
     * Splitting them by route meant a reader who wanted "the Golf" had to
     * guess which of three tabs held it, and each tab answered by dumping its
     * whole table on arrival — 47 subjects, then 40 weak claims, then the
     * gaps, none of it asked for.
     *
     * So: one list, three lenses over it, nothing expanded until asked. The
     * counts in the header are the only thing shown unprompted, because a
     * count is an orientation and a table is a demand.
     */

    type Lens = "all" | "gaps" | "weak";

    // The lens can arrive from the route: `#/coverage` and `#/health` are
    // links this app has been handing out for versions, and they resolve here
    // now (see nav.ts's ALIASES). A bookmark must land on the lens it named.
    let {
        lens: initial = "all",
        subjectId = "",
        catalogs: openCatalogs = false,
    }: { lens?: string; subjectId?: string; catalogs?: boolean } = $props();

    const asLens = (named: string): Lens =>
        (["all", "gaps", "weak"].includes(named) ? named : "all") as Lens;
    let lens = $state<Lens>("all" as Lens);
    $effect.pre(() => {
        lens = asLens(initial);
    });
    const LENS_IDS: Lens[] = ["all", "gaps", "weak"];

    // WAI-ARIA tabs: Left/Right/Home/End move both focus and the selection —
    // the same mechanism ops-21 gave Activity's lens tabs (knowledge-28).
    function onLensKey(event: KeyboardEvent, index: number) {
        const move = (to: number) => {
            const next = LENS_IDS[(to + LENS_IDS.length) % LENS_IDS.length];
            lens = next;
            document.getElementById(`knowledge-tab-${next}`)?.focus();
        };
        if (event.key === "ArrowRight") move(index + 1);
        else if (event.key === "ArrowLeft") move(index - 1);
        else if (event.key === "Home") move(0);
        else if (event.key === "End") move(LENS_IDS.length - 1);
        else return;
        event.preventDefault();
    }

    let query = $state("");
    let shown = $state(25);

    // The filters are rows from `/api/subjects/filters` (B180): their names,
    // descriptions and options are the API's words, so a new kind of subject
    // gains its option with no edit here. `selected` is keyed by the row's
    // id, and each row names the query parameter it feeds. A link from
    // Overview arrives with those parameters in the address and is applied
    // once the rows are known.
    let filters = $state<SubjectFilter[]>([]);
    let selected = $state<Record<string, string>>({});
    let helpOpen = $state("");
    const scopeFilter = $derived(filters.find((one) => one.param === "pack_id"));
    const scoped = $derived(scopeFilter ? (selected[scopeFilter.id] ?? "") : "");
    const params = () =>
        Object.fromEntries(
            filters.map((one) => [one.param, selected[one.id] ?? ""]),
        );

    // The one line that stands for installed catalogs and drafts. Closed by
    // default so the search is the first thing on screen; `?catalogs=1` opens
    // it for a link that points at a catalog.
    let catalogsOpen = $state(openCatalogs || $route.query.catalogs === "1");

    let status = $state<Status | null>(null);
    let packs = $state<Pack[]>([]);
    // Packs an agent drafted, and whichever one the reader is acting on.
    let drafts = $state<PackDraft[]>([]);
    let draftBusy = $state("");
    // The exception itself, not a sentence squeezed out of it: `Failure.svelte`
    // is the one place that decides what a failure means to the reader, and a
    // view that writes its own copy ships worse copy than the rest.
    let draftError = $state<unknown>(null);
    let subjects = $state<Subject[]>([]);
    let gaps = $state<Gap[]>([]);
    let error = $state<unknown>(null);
    let loading = $state(true);

    // Which row is open, and what was fetched for it. Keyed by subject id
    // rather than held as "the open row" so collapsing and re-expanding does
    // not re-fetch, and so two rows can be compared without losing the first.
    let open = $state<Record<string, boolean>>({});
    let detail = $state<Record<string, SubjectDetail | string>>({});
    // Research is deliberately not the same state as expansion: a reader who
    // opened a row to read it must not have a job started underneath them.
    let researching = $state<Record<string, boolean>>({});

    let timer: ReturnType<typeof setTimeout> | undefined;

    async function loadList() {
        loading = true;
        try {
            // 500 rather than the default 60, and paged in the client: this is
            // a local SQLite read of one table, so the network is not the cost
            // here — the cost is the reader's attention, and that is what
            // `shown` bounds.
            subjects = await api.subjects(query.trim(), 500, params());
            error = null;
        } catch (cause) {
            error = cause;
        } finally {
            loading = false;
        }
    }

    async function loadFrame() {
        // Hidden drafts are read back with the frame rather than on mount, so
        // a card the reader dismissed never flashes on screen before the
        // setting arrives.
        void api.settings().then((all) => {
            const stored = all?.[HIDDEN_KEY];
            hidden = typeof stored === "string" && stored
                ? stored.split(",").filter(Boolean)
                : [];
        }).catch(() => {});
        const [s, p, d, f] = await Promise.all([
            api.status().catch(() => null),
            api.packs().catch(() => [] as Pack[]),
            // Best effort: a reader with no drafts is the common case, and a
            // failure here must not cost them the screen.
            // `?? []`, not just `.catch`: a response that arrives but carries
            // no `items` does not throw, and a non-array here reaches
            // `visibleDrafts.filter` as a TypeError with no stack worth
            // reading. A screen must not need its server to be correct to
            // render.
            api.packDrafts()
                .then((r) => (Array.isArray(r?.items) ? r.items : []))
                .catch(() => [] as PackDraft[]),
            api
                .subjectFilters()
                .then((r) => (Array.isArray(r?.filters) ? r.filters : []))
                .catch(() => [] as SubjectFilter[]),
        ]);
        if (!filters.length && f.length) {
            // First arrival: take whatever the address named.
            filters = f;
            selected = Object.fromEntries(
                f
                    .filter((one) => $route.query[one.param])
                    .map((one) => [one.id, $route.query[one.param]]),
            );
            if (Object.keys(selected).length) void loadList();
        } else {
            filters = f;
        }
        status = s;
        packs = p;
        drafts = d;
        // Gaps are per pack, and a disabled pack still reports them — a gap is
        // a fact about the pack's own contents, not about whether the reader
        // has it switched on.
        const lists = await Promise.all(
            p.map((pack) =>
                api
                    .gaps(pack.pack_id)
                    .then((rows) => rows.map((row) => ({ ...row, pack_id: pack.pack_id })))
                    .catch(() => [] as Gap[]),
            ),
        );
        gaps = lists.flat();
    }

    function onInput() {
        clearTimeout(timer);
        shown = 25;
        timer = setTimeout(loadList, 180);
    }

    /* One subject, named in the address.
     *
     * `#/knowledge/<subject_id>` exists because the browser panel's search
     * needed somewhere to send a row: a reader who typed a name, saw the
     * variant they meant among three that share a label, and pressed it was
     * otherwise dropped on an unfiltered list to find it a second time.
     *
     * It opens the row rather than filtering to it. Filtering would answer
     * "show me this one" and lose the thing the reader came for, which is
     * *this one among the others* — the same reason every search result
     * carries its identity.
     */
    $effect(() => {
        if (!subjectId || open[subjectId]) return;
        const row = subjects.find((one) => one.subject_id === subjectId);
        if (!row) return;
        // The row may be past the 25 the list starts collapsed to — raise
        // `shown` far enough to include it, or the link opens a row the
        // reader cannot scroll to.
        const index = filtered.indexOf(row);
        if (index >= shown) shown = index + 1;
        void expand(row);
    });

    async function expand(subject: Subject) {
        open = { ...open, [subject.subject_id]: !open[subject.subject_id] };
        if (detail[subject.subject_id]) return;
        try {
            detail = {
                ...detail,
                [subject.subject_id]: await api.subject(subject.subject_id),
            };
        } catch (cause) {
            detail = {
                ...detail,
                // A row-sized failure: the headline only, derived from the
                // status like every other sentence in the app (B72).
                [subject.subject_id]: remedyFor(cause).headline,
            };
        }
    }

    const ready = Promise.all([loadList(), loadFrame()]);

    // A pack that is installed and switched off is the single most confusing
    // state this app has: `/api/subjects` filters on `enabled = 1`, so every
    // list goes empty at once and nothing on screen says why. Said here
    // because this is the screen where the emptiness is loudest.
    const disabled = $derived(packs.filter((pack) => !pack.enabled));

    // Filtered by the server, so the count and the rows agree.
    const filtered = $derived(subjects);
    const anySelected = $derived(Object.values(selected).some(Boolean));
    const visible = $derived(filtered.slice(0, shown));

    const gapIds = $derived(new Set(gaps.map((gap) => gap.subject_id)));
    const gapRows = $derived(
        gaps.filter(
            (gap) =>
                !query.trim() ||
                gap.label.toLowerCase().includes(query.trim().toLowerCase()),
        ),
    );

    //: Drafts the reader has hidden, by slug. Kept in settings rather than in
    //: component state because "it came back when I reloaded" is the same
    //: complaint as "it never went away" — a dismissal that does not persist
    //: is not one.
    const HIDDEN_KEY = "knowledge_hidden_drafts";
    let hidden = $state<string[]>([]);
    const visibleDrafts = $derived(
        drafts.filter((one) => !hidden.includes(one.slug)),
    );

    async function hideDraft(draft: PackDraft) {
        hidden = [...hidden, draft.slug];
        // Fire-and-forget, like every other dismissal here: a failed write
        // means it comes back next session, never that the click did nothing.
        void api.putSettings({ [HIDDEN_KEY]: hidden.join(",") }).catch(() => {});
    }

    async function installDraft(draft: PackDraft) {
        draftBusy = draft.slug;
        draftError = null;
        try {
            await api.installPackDraft(draft.slug);
            await loadFrame();
            await loadList();
        } catch (thrown) {
            draftError = thrown;
        } finally {
            draftBusy = "";
        }
    }

    // "It has nineteen products and lacks the twentieth." Amending asks for the
    // twentieth and leaves the nineteen alone — nothing existing is rewritten,
    // and a refused amendment leaves the draft as it was, which is what makes
    // this safe to press on a pack you already like.
    let amending = $state<string | null>(null);
    let amendNote = $state("");
    let amendJob = $state("");

    async function amendDraft(draft: PackDraft) {
        draftBusy = draft.slug;
        draftError = null;
        try {
            const started = await api.amendPackDraft(draft.slug, amendNote.trim());
            amendJob = started.job_id;
            amending = null;
            amendNote = "";
        } catch (thrown) {
            draftError = thrown;
        } finally {
            draftBusy = "";
        }
    }

    // Re-read the pages behind what is installed. Nothing generative is
    // involved: the question is "does the quote still appear", which a
    // substring test answers honestly and an LLM would answer confidently.
    let verifyJob = $state("");
    let verifying = $state(false);
    async function verifyPack(packId: string) {
        if (verifying) return;
        verifying = true;
        draftError = null;
        try {
            verifyJob = (await api.verify({ pack_id: packId })).job_id;
        } catch (thrown) {
            draftError = thrown;
        } finally {
            verifying = false;
        }
    }

    let confirmDiscard = $state("");
    async function discardDraft(draft: PackDraft) {
        confirmDiscard = "";
        draftBusy = draft.slug;
        draftError = null;
        try {
            await api.discardPackDraft(draft.slug);
            await loadFrame();
        } catch (thrown) {
            draftError = thrown;
        } finally {
            draftBusy = "";
        }
    }

    async function enable(pack: Pack) {
        await api.setEnabled(pack.pack_id, true);
        await Promise.all([loadList(), loadFrame()]);
    }
</script>

<PageHead crumb="knowledge / browse" title="Browse" lead="Search every subject, attribute and claim stored on this machine." />

<!-- Search first (B180). Installed catalogs, switched-off ones and drafts are
     one line that unfolds: they change what the lists below can hold, but the
     reader came to look something up, so the line is shown and its contents
     wait. The counts sit beside it as a single row. -->
<div class="topline">
    {#if status}
        <ul class="statstrip" aria-label="What this install holds">
            <li><strong>{(status.counts_enabled ?? status.counts).subjects}</strong><span class="meta">subjects</span></li>
            <li><strong>{(status.counts_enabled ?? status.counts).claims}</strong><span class="meta">claims</span></li>
            <li><strong>{(status.counts_enabled ?? status.counts).evidence}</strong><span class="meta">sources</span></li>
            <li class={gaps.length ? "warn" : ""}>
                <strong>{gaps.length}</strong><span class="meta">nothing known</span>
            </li>
        </ul>
    {/if}
    <button
        class="ghost catalogs-toggle"
        aria-expanded={catalogsOpen}
        aria-controls="catalogs-panel"
        onclick={() => (catalogsOpen = !catalogsOpen)}
    >
        {count(packs.length, "catalog")}{#if disabled.length}, {disabled.length} off{/if}{#if visibleDrafts.length}, {count(visibleDrafts.length, "draft")}{/if}
        <span class="chev" aria-hidden="true">{catalogsOpen ? "–" : "+"}</span>
    </button>
</div>

{#if catalogsOpen}
<div id="catalogs-panel" class="catalogs-panel enter">
<section class="packs-section" aria-label="Catalogs">
    <PacksSection
        onchange={() => {
            void loadFrame();
            void loadList();
        }}
    />
</section>

{#each disabled as pack (pack.pack_id)}
    <article class="card notice">
        <div>
            <strong>{pack.name} is switched off</strong>
            <span class="meta">
                {count(pack.claims, "claim")} on {count(pack.subjects, "subject")} are not answered while it is off.
            </span>
        </div>
        <button onclick={() => enable(pack)}>Switch on</button>
    </article>
{/each}

<!-- Drafts an agent wrote. `notice` only while one still waits on the reader
     (B129): an installed draft is a receipt, not an alert, so it drops the
     alarm styling. -->
{#each visibleDrafts as draft (draft.slug)}
    <article class={draft.installed_as ? "card quiet-draft" : "card notice"}>
        <div>
            <strong>
                {draft.name || draft.slug}
                {draft.installed_as ? "is installed" : "is a draft"}
            </strong>
            <span class="meta">
                {#if draft.error}
                    Does not load yet: {draft.error}
                {:else}
                    {draft.pack_id} {draft.version} · {count(draft.files.length, "file")}
                    <span title={draft.root}>on disk</span>
                {/if}
            </span>
        </div>
        <span class="row">
            <button
                onclick={() => installDraft(draft)}
                disabled={draftBusy === draft.slug || !!draft.error}
                >{draft.installed_as ? "Install again" : "Install"}</button
            >
            <button
                class="ghost"
                onclick={() =>
                    (amending = amending === draft.slug ? null : draft.slug)}
                aria-expanded={amending === draft.slug}
                disabled={draftBusy === draft.slug}>Extend</button
            >
            <!-- Two verbs on purpose: hiding only stops the reminder, while
                 discarding deletes what the agent wrote. Hiding persists in
                 settings or it is not a dismissal. -->
            {#if draft.installed_as}
                <button
                    class="ghost"
                    onclick={() => hideDraft(draft)}
                    disabled={draftBusy === draft.slug}>Hide</button
                >
            {/if}
            <button
                class="ghost"
                onclick={() =>
                    confirmDiscard === draft.slug
                        ? discardDraft(draft)
                        : (confirmDiscard = draft.slug)}
                disabled={draftBusy === draft.slug}
                >{confirmDiscard === draft.slug ? "Confirm discard" : "Discard"}</button
            >
            {#if confirmDiscard === draft.slug}
                <button class="ghost" onclick={() => (confirmDiscard = "")}>Cancel</button>
            {/if}
        </span>
        {#if amending === draft.slug}
            <div class="amend">
                <label for="amend-{draft.slug}">What is missing</label>
                <textarea
                    id="amend-{draft.slug}"
                    bind:value={amendNote}
                    rows="3"
                    placeholder="Leave empty to use the draft's own list of uncovered products."
                ></textarea>
                <button
                    onclick={() => amendDraft(draft)}
                    disabled={draftBusy === draft.slug}>Ask an agent</button
                >
            </div>
        {/if}
    </article>
{/each}
</div>
{/if}
{#if amendJob}
    <p class="state">
        Extending the draft. <a href="#/activity">Watch it on Activity</a>.
    </p>
{/if}
{#if verifyJob}
    <p class="state">
        Re-reading the sources. <a href="#/activity">Watch it on Activity</a>.
    </p>
{/if}
{#if draftError}
    <Failure error={draftError} />
{/if}


<!-- WAI-ARIA tabs, the same contract Activity's lens tabs now carry
     (ops-21/knowledge-28): only the selected tab is in the Tab order, and
     Left/Right/Home/End move both focus and the selection. -->
<div class="lenses" role="tablist" aria-label="Lens">
    <button
        id="knowledge-tab-all"
        class="tab"
        role="tab"
        aria-selected={lens === "all"}
        aria-controls="knowledge-panel"
        tabindex={lens === "all" ? 0 : -1}
        class:active={lens === "all"}
        onclick={() => (lens = "all")}
        onkeydown={(event) => onLensKey(event, 0)}>What is here</button
    >
    <button
        id="knowledge-tab-gaps"
        class="tab"
        role="tab"
        aria-selected={lens === "gaps"}
        aria-controls="knowledge-panel"
        tabindex={lens === "gaps" ? 0 : -1}
        class:active={lens === "gaps"}
        onclick={() => (lens = "gaps")}
        onkeydown={(event) => onLensKey(event, 1)}
        >What is missing{gaps.length ? ` (${gaps.length})` : ""}</button
    >
    <button
        id="knowledge-tab-weak"
        class="tab"
        role="tab"
        aria-selected={lens === "weak"}
        aria-controls="knowledge-panel"
        tabindex={lens === "weak" ? 0 : -1}
        class:active={lens === "weak"}
        onclick={() => (lens = "weak")}
        onkeydown={(event) => onLensKey(event, 2)}>What is thin</button
    >
</div>

<div role="tabpanel" id="knowledge-panel" aria-label="Knowledge">
{#if lens === "all" || lens === "gaps"}
    <div class="row filters">
        <div class="field grow">
            <label for="k-search">Search</label>
            <input
                id="k-search"
                bind:value={query}
                oninput={onInput}
                placeholder="Name"
            />
        </div>
        {#if lens === "all"}
            {#each filters as one (one.id)}
                <!-- Each filter is named and described by its row. The
                     description is one press away rather than printed, so the
                     bar stays one line. -->
                <div class="field">
                    <span class="flabel">
                        <label for="k-{one.id}">{one.label}</label>
                        <button
                            class="help"
                            aria-expanded={helpOpen === one.id}
                            aria-label="About {one.label}"
                            onclick={() => (helpOpen = helpOpen === one.id ? "" : one.id)}
                            >?</button
                        >
                    </span>
                    <select
                        id="k-{one.id}"
                        value={selected[one.id] ?? ""}
                        onchange={(event) => {
                            selected = { ...selected, [one.id]: event.currentTarget.value };
                            shown = 25;
                            void loadList();
                        }}
                    >
                        <option value="">All</option>
                        {#each one.options as option (option.value)}
                            <option value={option.value}>{option.label} ({option.count})</option>
                        {/each}
                    </select>
                </div>
            {/each}
            {#if anySelected}
                <div class="field">
                    <span class="meta">&nbsp;</span>
                    <button
                        class="ghost"
                        onclick={() => {
                            selected = {};
                            shown = 25;
                            void loadList();
                        }}>Clear</button
                    >
                </div>
            {/if}
        {/if}
        <!-- The third operation kind (docs/AGENT_OPERATIONS.md §1): re-read
             the pages behind what is installed here. Free, and it retracts
             nothing: a `missing` verdict is a signal beside the reader's own
             marks, because pages get rewritten and the engine has no
             authority to remove a claim on the strength of one fetch. -->
        <div class="field">
            <span class="meta">&nbsp;</span>
            <button class="ghost" disabled={verifying} onclick={() => verifyPack(scoped)}>
                {verifying ? "Starting…" : "Verify sources"}
            </button>
        </div>
    </div>
    {#each filters as one (one.id)}
        {#if helpOpen === one.id}
            <p class="fhelp enter" role="note">
                <strong>{one.label}.</strong>
                {one.description}
                {#each one.options.filter((option) => option.description) as option (option.value)}
                    <span class="meta"> {option.label}: {option.description}</span>
                {/each}
            </p>
        {/if}
    {/each}
{/if}

{#await ready}
    <p class="state loading">Reading the store…</p>
{:then}
    {#if error}
        <Failure {error} retry={loadList} />
    {:else if lens === "weak"}
        <Health heading={false} focusClaimId={subjectId} />
    {:else if lens === "gaps"}
        {#if !gapRows.length}
            <EmptyState title={gaps.length ? "No gap matches that" : "Nothing is missing"} />
        {:else}
            <ul class="klist">
                {#each gapRows as gap (gap.subject_id)}
                    <li class="krow">
                        <div class="kmain">
                            <span class="klabel">{gap.label}</span>
                            <span class="meta">{gap.kind} · nothing known</span>
                        </div>
                        <button
                            onclick={() =>
                                (researching = {
                                    ...researching,
                                    [gap.subject_id]: !researching[gap.subject_id],
                                })}
                        >
                            {researching[gap.subject_id] ? "Hide brief" : "Research"}
                        </button>
                        {#if researching[gap.subject_id]}
                            <div class="kdetail">
                                <Brief
                                    subjectId={gap.subject_id}
                                    packId={gap.pack_id}
                                    label={gap.label}
                                    onClose={() =>
                                        (researching = {
                                            ...researching,
                                            [gap.subject_id]: false,
                                        })}
                                />
                            </div>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}
    {:else if !filtered.length}
        <EmptyState
            title={query ? `Nothing matches “${query}”` : "No subjects to show"}
            actionLabel={anySelected ? "Clear filters" : ""}
            onAction={anySelected
                ? () => {
                      selected = {};
                      void loadList();
                  }
                : undefined}
        />
    {:else}
        <p class="meta count">
            {visible.length === filtered.length
                ? count(filtered.length, "subject")
                : `${visible.length} of ${count(filtered.length, "subject")}`}
        </p>
        <ul class="klist">
            {#each visible as subject (subject.subject_id)}
                {@const isOpen = Boolean(open[subject.subject_id])}
                {@const got = detail[subject.subject_id]}
                <li class="krow" class:open={isOpen}>
                    <button
                        class="kopen"
                        aria-expanded={isOpen}
                        onclick={() => expand(subject)}
                    >
                        <span class="chev" aria-hidden="true">{isOpen ? "–" : "+"}</span>
                        <span class="kmain">
                            <span class="klabel">{subject.label}</span>
                            <span class="meta">{subject.kind} · {subject.pack_id}</span>
                        </span>
                        <span class="badge" class:warn={subject.claims === 0}>
                            {count(subject.claims, "claim")}
                        </span>
                    </button>
                    <button
                        class="ghost"
                        onclick={() =>
                            (researching = {
                                ...researching,
                                [subject.subject_id]: !researching[subject.subject_id],
                            })}
                    >
                        {researching[subject.subject_id] ? "Hide brief" : "Research"}
                    </button>

                    {#if researching[subject.subject_id]}
                        <div class="kdetail">
                            <Brief
                                subjectId={subject.subject_id}
                                packId={subject.pack_id}
                                label={subject.label}
                                onClose={() =>
                                    (researching = {
                                        ...researching,
                                        [subject.subject_id]: false,
                                    })}
                            />
                        </div>
                    {/if}

                    {#if isOpen}
                        <div class="kdetail enter">
                            {#if typeof got === "string"}
                                <p class="state error">{got}</p>
                            {:else if !got}
                                <p class="skeleton" style="height: 4rem">Reading…</p>
                            {:else}
                                {#if got.attributes.length}
                                    <ul class="attrs">
                                        {#each got.attributes as attr (attr.key)}
                                            <li class:identity={attr.is_identity}>
                                                <span class="meta">{attr.key}</span>
                                                <span
                                                    >{attr.value_text}{attr.unit
                                                        ? ` ${attr.unit}`
                                                        : ""}</span
                                                >
                                            </li>
                                        {/each}
                                    </ul>
                                {/if}
                                {#if got.claims.length}
                                    <ol class="claims">
                                        {#each got.claims as claim (claim.claim_id)}
                                            <li>
                                                <span class="sev {claim.severity}"
                                                    >{severityWord(claim.severity)}</span
                                                >
                                                {claim.title ?? claim.claim_id}
                                                <span class="meta">{claim.domain}</span>
                                            </li>
                                        {/each}
                                    </ol>
                                {:else}
                                    <p class="state empty">Nothing is known about this one yet.</p>
                                {/if}
                            {/if}
                        </div>
                    {/if}
                </li>
            {/each}
        </ul>
        {#if visible.length < filtered.length}
            <button class="ghost more" onclick={() => (shown += 50)}>
                Show {Math.min(50, filtered.length - visible.length)} more
            </button>
        {/if}
    {/if}
{/await}
</div>

<style>
    /* One row: the counts on the left, the catalogs line on the right. This
       is what keeps the search within the first screenful (B180). */
    .topline {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3) var(--s-5);
        margin: 0 0 var(--s-3);
    }
    .catalogs-toggle {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }
    .catalogs-panel {
        margin: 0 0 var(--s-4);
    }
    .statstrip {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-5);
        margin: 0;
        padding: 0;
        list-style: none;
    }
    .statstrip li {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
    }
    .statstrip strong {
        font-size: var(--t-lg);
        line-height: var(--lh-lg);
    }
    .grow {
        flex: 1 1 14rem;
    }
    .flabel {
        display: flex;
        align-items: center;
        gap: var(--s-1);
    }
    .help {
        width: 1.25rem;
        height: 1.25rem;
        padding: 0;
        border: 1px solid var(--line, currentColor);
        border-radius: 50%;
        background: none;
        color: var(--dim);
        font-size: var(--t-sm, 0.75rem);
        line-height: 1;
        cursor: pointer;
    }
    .help[aria-expanded="true"] {
        color: inherit;
    }
    .fhelp {
        margin: 0 0 var(--s-3);
        max-width: var(--measure);
    }
    .statstrip li.warn strong {
        color: var(--medium);
    }
    .notice {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-4);
        flex-wrap: wrap;
        border-color: var(--medium);
    }
    .notice .meta {
        display: block;
        max-width: var(--measure);
    }
    /* Same layout as `.notice`, none of its alarm. A draft that is already in
       the store is a receipt, not a warning, and `--medium` on its border was
       the reader's "the warning stays there" — the card had changed its words
       and kept its colour, which is the half anybody actually reads. */
    .quiet-draft {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-4);
        flex-wrap: wrap;
        opacity: 0.82;
    }
    .quiet-draft .meta {
        display: block;
        max-width: var(--measure);
    }
    .filters {
        margin-bottom: var(--s-3);
    }
    .count {
        margin: 0 0 var(--s-2);
    }
    /* The whole row is the affordance, not a link buried in it: the reader's
     * target here is a name, and a 6px chevron is a worse target than the
     * 40rem of row the name sits in. */
    .kopen {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        flex: 1 1 22rem;
        min-width: 0;
        background: none;
        border: 0;
        padding: var(--s-2) 0;
        text-align: left;
        color: inherit;
        cursor: pointer;
    }
    .kopen:hover .klabel {
        text-decoration: underline;
    }
    .chev {
        width: 1rem;
        text-align: center;
        color: var(--dim);
    }
    .badge.warn {
        background: var(--medium-soft);
        color: var(--medium);
    }
    /* Full-width, so an expanded row's contents are not squeezed into
     * whatever the flex row had left over. */
    .kdetail {
        flex: 1 0 100%;
        padding: var(--s-2) 0 var(--s-4) var(--s-5);
    }
    .attrs {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-1) var(--s-4);
        margin: 0 0 var(--s-3);
        padding: 0;
        list-style: none;
    }
    .attrs li {
        display: flex;
        flex-direction: column;
    }
    .attrs li.identity span:last-child {
        font-weight: 600;
    }
    .claims {
        margin: 0;
        padding-left: var(--s-5);
        line-height: var(--lh-read);
    }
    .more {
        margin-top: var(--s-3);
    }
</style>
