<script lang="ts">
    import Failure from "../lib/Failure.svelte";
    import { remedyFor } from "../lib/failure";
    import Brief from "../lib/Brief.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Health from "./Health.svelte";
    import { api } from "../lib/api";
    import { count } from "../lib/plural";
    import { severityWord } from "../lib/report";
    import type {
        Gap,
        MarkQueueItem,
        Marks,
        Pack,
        PackDraft,
        MarkSignals,
        Status,
        Subject,
        SubjectDetail,
    } from "../lib/types";

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

    type Lens = "all" | "gaps" | "weak" | "marked";

    // The lens can arrive from the route: `#/coverage` and `#/health` are
    // links this app has been handing out for versions, and they resolve here
    // now (see nav.ts's ALIASES). A bookmark must land on the lens it named.
    let {
        lens: initial = "all",
        subjectId = "",
    }: { lens?: string; subjectId?: string } = $props();

    const asLens = (named: string): Lens =>
        (["all", "gaps", "weak", "marked"].includes(named) ? named : "all") as Lens;
    let lens = $state<Lens>("all" as Lens);
    $effect.pre(() => {
        lens = asLens(initial);
    });
    let query = $state("");
    let packFilter = $state("");
    let shown = $state(25);

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

    // Verdicts readers left, almost all of them from the browser extension —
    // the panel is where someone is actually looking at the product, so it is
    // the only place feedback is cheap to collect. They arrive here because
    // "which claims are getting called wrong" is an authoring question, and
    // this is the authoring screen.
    let marks = $state<Marks | null>(null);
    let markError = $state<unknown>(null);

    // What the marks *add up to*. The raw list answers "what did people say";
    // these two queues answer the only question an author can act on — which
    // system has the problem. A mark that feeds nothing is a survey, and this
    // is the half that makes it a signal (backlog B54).
    let signals = $state<MarkSignals | null>(null);

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
            subjects = await api.subjects(query.trim(), 500);
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
        const [s, p, d] = await Promise.all([
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
        ]);
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

    async function loadMarks() {
        try {
            // Both in one pass: the queues are derived from the same rows, so
            // a screen that showed the list and then, a beat later, its
            // consequences would be describing one fetch as two.
            [marks, signals] = await Promise.all([api.marks(), api.markSignals()]);
            markError = null;
        } catch (cause) {
            markError = cause;
        }
    }

    /** Which door implicates what.
     *
     * A `not mine` on a subject only ever reached from a page is an extraction
     * problem — something on the page was read as an identity it is not. The
     * same verdict on a typed-in query is a *gate* problem: what was entered
     * matched more than it should. The distinction is the whole reason the
     * door is carried through, so the screen says it in words rather than
     * printing a tally and leaving the reading to the author.
     */
    function doorReading(item: MarkQueueItem): string {
        const doors = Object.keys(item.sources ?? {});
        if (!doors.length) return "No saved answer here names this subject.";
        if (doors.length > 1) return "Reached both ways — look at the gate before the reader.";
        return doors[0] === "url"
            ? "Only ever reached from a page: suspect what the page was read as."
            : "Only ever reached from a typed-in query: suspect the gate being too broad.";
    }

    /** Drop a verdict.
     *
     * The author's move after acting on it: a claim they rewrote should stop
     * being listed as wrong, and there is no other way to retract a mark from
     * inside the app. It removes the *reader's note*, never the claim.
     */
    async function forget(packId: string, claimId: string) {
        await api.unmark(packId, claimId);
        await loadMarks();
    }

    const VERDICT_WORDS: Record<string, string> = {
        useful: "Useful",
        // Kept apart on purpose: `wrong` is a claim problem, `not_applicable`
        // is a *matching* problem — the claim may be perfectly true of the
        // product it was written for, and this was not that one. Merging them
        // would hide which half of the system needs the fix.
        not_applicable: "Not mine",
        wrong: "Wrong",
    };

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

    const ready = Promise.all([loadList(), loadFrame(), loadMarks()]);

    // A pack that is installed and switched off is the single most confusing
    // state this app has: `/api/subjects` filters on `enabled = 1`, so every
    // list goes empty at once and nothing on screen says why. Said here
    // because this is the screen where the emptiness is loudest.
    const disabled = $derived(packs.filter((pack) => !pack.enabled));

    const filtered = $derived(
        subjects.filter((s) => !packFilter || s.pack_id === packFilter),
    );
    const visible = $derived(filtered.slice(0, shown));

    // The mark queues carry only a subject id — a key an agent reads, not a
    // name a reader recognizes. Resolved against the subject list already on
    // screen rather than shipping a second lookup (knowledge-17).
    const subjectLabels = $derived(
        new Map(subjects.map((s) => [s.subject_id, s.label])),
    );
    const subjectLabel = (id: string) => subjectLabels.get(id) ?? id;

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

<h2>Knowledge</h2>

<!-- The header is counts, not content: five numbers say where you are
     without asking the reader to read a table to find out. -->
{#if status}
    <ul class="statstrip enter" aria-label="What this install holds">
        <li>
            <strong>{status.enabled_packs}</strong>
            <span class="meta">of {count(status.counts.packs, "pack")} on</span>
        </li>
        <li><strong>{status.counts.subjects}</strong><span class="meta">subjects</span></li>
        <li><strong>{status.counts.claims}</strong><span class="meta">claims</span></li>
        <li><strong>{status.counts.evidence}</strong><span class="meta">sources</span></li>
        <li class={gaps.length ? "warn" : ""}>
            <strong>{gaps.length}</strong><span class="meta">nothing known</span>
        </li>
    </ul>
{/if}

{#each disabled as pack (pack.pack_id)}
    <article class="card notice">
        <div>
            <strong>{pack.name} is installed but switched off</strong>
            <span class="meta">
                It holds {count(pack.claims, "claim")} about {count(pack.subjects, "subject")}, and
                answers none of them while it is off — which is why the lists below are
                empty rather than broken.
            </span>
        </div>
        <button onclick={() => enable(pack)}>Switch it on</button>
    </article>
{/each}

<!-- Drafts an agent wrote. Above the lenses because a pack waiting to be
     installed changes what every list below can possibly contain, and because
     an agent's proposal that nobody ever sees is the same as no proposal.

     `notice` only while it is still waiting on the reader. B129 made the card
     say "is installed" and left it looking exactly as it had before — a
     warning-coloured box, in the alert position, above everything. The reader
     pressed Install, the pack appeared in their store, and the same alarm was
     still on the screen: "I click either one and the warning stays there." An
     installed draft is not an alert, it is a receipt, so it stops being styled
     as one and drops out of the way. -->
{#each visibleDrafts as draft (draft.slug)}
    <article class={draft.installed_as ? "card quiet-draft" : "card notice"}>
        <div>
            <strong>
                {draft.name || draft.slug}
                {draft.installed_as ? "is installed" : "was drafted for you"}
            </strong>
            <span class="meta">
                {#if draft.error}
                    It does not load yet: {draft.error}. Tell the agent that, and it
                    can fix the file it wrote.
                {:else}
                    {draft.pack_id} {draft.version} · {count(draft.files.length, "file")}
                    <span title={draft.root}>on disk</span>.
                    {#if draft.installed_as}
                        It is in your store — the draft is kept so you can cover
                        its gaps and install it again.
                    {:else}
                        Nothing of it is in your store until you install it, and
                        nothing in it can run — a drafted pack is data only.
                    {/if}
                {/if}
            </span>
        </div>
        <span class="row">
            <button
                onclick={() => installDraft(draft)}
                disabled={draftBusy === draft.slug || !!draft.error}
                >{draft.installed_as ? "Install it again" : "Install it"}</button
            >
            <!-- The correction verb. A generator you cannot correct is a slot
                 machine; a tool you can is worth keeping. -->
            <button
                class="ghost"
                onclick={() =>
                    (amending = amending === draft.slug ? null : draft.slug)}
                aria-expanded={amending === draft.slug}
                disabled={draftBusy === draft.slug}>Cover the gaps</button
            >
            <!-- Two different verbs, and conflating them was the other half
                 of the complaint. "Throw it away" deletes what the agent
                 wrote; nobody should have to destroy a proposal to stop being
                 reminded of it. Hiding is the one an installed draft wants,
                 and it has to survive a reload or it is not a dismissal. -->
            {#if draft.installed_as}
                <button
                    class="ghost"
                    onclick={() => hideDraft(draft)}
                    disabled={draftBusy === draft.slug}>Hide this</button
                >
            {/if}
            <button
                class="ghost"
                onclick={() =>
                    confirmDiscard === draft.slug
                        ? discardDraft(draft)
                        : (confirmDiscard = draft.slug)}
                disabled={draftBusy === draft.slug}
                >{confirmDiscard === draft.slug ? "Really throw it away?" : "Throw it away"}</button
            >
            {#if confirmDiscard === draft.slug}
                <button class="ghost" onclick={() => (confirmDiscard = "")}>Cancel</button>
            {/if}
        </span>
        {#if amending === draft.slug}
            <div class="amend">
                <label for="amend-{draft.slug}">
                    What is it missing? Leave this empty and the draft's own list
                    of uncovered products is the request.
                </label>
                <textarea
                    id="amend-{draft.slug}"
                    bind:value={amendNote}
                    rows="3"
                    placeholder="It has the Buds Pro and Buds2 Pro but not the Buds3, Buds3 Pro or Buds FE."
                ></textarea>
                <p class="meta">
                    Nothing already in the draft is changed. If the agent comes back
                    with nothing usable, the draft stays exactly as it is.
                </p>
                <button
                    onclick={() => amendDraft(draft)}
                    disabled={draftBusy === draft.slug}>Ask an agent</button
                >
            </div>
        {/if}
    </article>
{/each}
{#if amendJob}
    <p class="state">
        Extending the draft — <a href="#/activity">watch it on Activity</a>. The
        draft updates when it finishes.
    </p>
{/if}
{#if verifyJob}
    <p class="state">
        Re-reading the sources — <a href="#/activity">watch it on Activity</a>.
        Verdicts land beside each claim.
    </p>
{/if}
{#if draftError}
    <Failure error={draftError} />
{/if}

<div class="lenses" role="tablist" aria-label="Lens">
    <button
        class="tab"
        role="tab"
        aria-selected={lens === "all"}
        class:active={lens === "all"}
        onclick={() => (lens = "all")}>What is here</button
    >
    <button
        class="tab"
        role="tab"
        aria-selected={lens === "gaps"}
        class:active={lens === "gaps"}
        onclick={() => (lens = "gaps")}
        >What is missing{gaps.length ? ` (${gaps.length})` : ""}</button
    >
    <button
        class="tab"
        role="tab"
        aria-selected={lens === "weak"}
        class:active={lens === "weak"}
        onclick={() => (lens = "weak")}>What is thin</button
    >
    <button
        class="tab"
        role="tab"
        aria-selected={lens === "marked"}
        class:active={lens === "marked"}
        onclick={() => (lens = "marked")}
        >What readers said{marks?.items.length ? ` (${marks.items.length})` : ""}</button
    >
</div>

{#if lens === "all" || lens === "gaps"}
    <div class="row filters">
        <div class="field">
            <label for="k-search">Search</label>
            <input
                id="k-search"
                bind:value={query}
                oninput={onInput}
                placeholder="a name, as the packs spell it…"
            />
        </div>
        {#if packs.length > 1 && lens === "all"}
            <div class="field">
                <label for="k-pack">Pack</label>
                <select
                    id="k-pack"
                    bind:value={packFilter}
                    onchange={() => (shown = 25)}
                >
                    <option value="">Every pack</option>
                    {#each packs as pack (pack.pack_id)}
                        <option value={pack.pack_id}>{pack.name}</option>
                    {/each}
                </select>
            </div>
        {/if}
        <!-- The third operation kind (docs/AGENT_OPERATIONS.md §1): re-read
             the pages behind what is installed here. Free, and it retracts
             nothing — a `missing` verdict is a signal beside the reader's own
             marks, because pages get rewritten and the engine has no authority
             to remove a claim on the strength of one fetch. -->
        <div class="field">
            <span class="meta">Evidence</span>
            <button class="ghost" disabled={verifying} onclick={() => verifyPack(packFilter)}>
                {verifying ? "Starting…" : "Verify the knowledge here"}
            </button>
        </div>
    </div>
{/if}

{#await ready}
    <p class="state loading">Reading the store…</p>
{:then}
    {#if error}
        <Failure {error} retry={loadList} />
    {:else if lens === "weak"}
        <Health heading={false} focusClaimId={subjectId} />
    {:else if lens === "marked"}
        {#if markError}
            <Failure error={markError} retry={loadMarks} />
        {:else if !marks}
            <p class="skeleton" style="height: 4rem">Reading…</p>
        {:else}
            <!-- Counts before the list, and every verdict present even at
                 zero: "three claims called wrong" reads differently against
                 three marks than against three hundred, and a strip that
                 changes shape as data arrives is unreadable. -->
            <ul class="statstrip" aria-label="Verdicts readers left">
                {#each marks.verdicts as verdict (verdict)}
                    <li class={verdict === "wrong" && marks.counts[verdict] ? "warn" : ""}>
                        <strong>{marks.counts[verdict] ?? 0}</strong>
                        <span class="meta">{VERDICT_WORDS[verdict] ?? verdict}</span>
                    </li>
                {/each}
            </ul>

            <!-- The queues before the list. An author opening this screen is
                 here to act, and "which subject is getting called wrong most"
                 is the only ordering that helps them — the raw list is
                 chronological, which is the ordering of nobody's work.
                 Both are derived, never curated: no one signs anything off
                 here, and nothing waits for them to (the automation
                 principle). -->
            {#if signals?.research?.length}
                <section class="queue">
                    <h3>Worth researching again</h3>
                    <p class="meta">
                        Readers say these claims are wrong. That is a knowledge problem:
                        the research below rewrites what is held, it does not touch the
                        reader's note.
                    </p>
                    <ul class="klist">
                        {#each signals.research as item (item.pack_id + item.subject_id)}
                            <li class="krow">
                                <div class="kmain">
                                    <span class="klabel">{subjectLabel(item.subject_id)}</span>
                                    <span class="meta"
                                        >{item.pack_id} · {item.count} called wrong</span
                                    >
                                </div>
                                <button
                                    onclick={() =>
                                        (researching = {
                                            ...researching,
                                            [item.subject_id]: !researching[item.subject_id],
                                        })}
                                >
                                    {researching[item.subject_id] ? "Hide brief" : "Research"}
                                </button>
                                {#each item.notes as note, i (i)}
                                    <p class="kdetail meta">“{note}”</p>
                                {/each}
                                {#if researching[item.subject_id]}
                                    <div class="kdetail">
                                        <Brief
                                            subjectId={item.subject_id}
                                            packId={item.pack_id}
                                            label={subjectLabel(item.subject_id)}
                                            onClose={() =>
                                                (researching = {
                                                    ...researching,
                                                    [item.subject_id]: false,
                                                })}
                                        />
                                    </div>
                                {/if}
                            </li>
                        {/each}
                    </ul>
                </section>
            {/if}

            {#if signals?.matching?.length}
                <section class="queue">
                    <h3>Matched the wrong thing</h3>
                    <p class="meta">
                        “Not mine” is not a claim being false — it is this claim reaching
                        someone it was not written for. Researching it again would fix
                        nothing; the door it arrived through is the lead.
                    </p>
                    <ul class="klist">
                        {#each signals.matching as item (item.pack_id + item.subject_id)}
                            <li class="krow">
                                <div class="kmain">
                                    <span class="klabel">{subjectLabel(item.subject_id)}</span>
                                    <span class="meta"
                                        >{item.pack_id} · {item.count} not theirs</span
                                    >
                                </div>
                                <span class="meta doors">
                                    {#each Object.entries(item.sources ?? {}) as [door, n] (door)}
                                        <span class="context-pair"
                                            ><span class="meta">{door}</span> {n}</span
                                        >
                                    {/each}
                                </span>
                                <p class="kdetail meta">{doorReading(item)}</p>
                            </li>
                        {/each}
                    </ul>
                </section>
            {/if}

            {#if !marks.items.length}
                <EmptyState
                    title="No one has marked anything yet"
                    detail="Every risk card in the browser extension asks “was this any
                            use?”. Answers land here — which claims readers found worth
                            having, which ones were wrong, and which ones simply were not
                            about their product."
                />
            {:else}
                <h3>Every mark</h3>
                <ul class="klist">
                    {#each marks.items as mark (mark.pack_id + mark.claim_id)}
                        <li class="krow">
                            <span class="kmain">
                                <span class="klabel"
                                    >{mark.title || mark.claim_id}</span
                                >
                                <span class="meta"
                                    >{mark.pack_id} · {mark.updated_at.slice(0, 10)}</span
                                >
                            </span>
                            <span class="verdict {mark.verdict}"
                                >{VERDICT_WORDS[mark.verdict] ?? mark.verdict}</span
                            >
                            <button
                                class="ghost"
                                onclick={() => forget(mark.pack_id, mark.claim_id)}
                                >Forget</button
                            >
                            {#if mark.note}
                                <p class="kdetail meta">{mark.note}</p>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
        {/if}
    {:else if lens === "gaps"}
        {#if !gapRows.length}
            <EmptyState
                title={gaps.length ? "No gap matches that" : "Nothing is missing"}
                detail="A gap is a subject a pack names but holds no claim for. None
                        listed means every subject the packs know about has something
                        written against it."
            />
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
            detail="Search matches a subject's label as the installed packs spell it.
                    A switched-off pack contributes nothing to this list."
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
                                    <p class="state empty">
                                        Nothing is known about this one yet — that is a gap,
                                        and Research above writes the brief for it.
                                    </p>
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

<style>
    .statstrip {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-5);
        margin: 0 0 var(--s-4);
        padding: 0;
        list-style: none;
    }
    .statstrip li {
        display: flex;
        flex-direction: column;
    }
    .statstrip strong {
        font-size: var(--t-lg);
        line-height: var(--lh-lg);
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
    .lenses {
        display: flex;
        gap: var(--s-2);
        margin-bottom: var(--s-3);
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
    /* Borrows the severity vocabulary rather than inventing a second one:
     * "wrong" is the only verdict that is a problem, so it is the only one
     * that gets a problem's colour. */
    .verdict {
        font-size: var(--t-sm);
        padding: 0 var(--s-2);
        border-radius: 999px;
        border: 1px solid var(--line);
        color: var(--dim);
        white-space: nowrap;
    }
    .verdict.useful {
        color: var(--low);
        border-color: var(--low);
    }
    .verdict.wrong {
        color: var(--high);
        border-color: var(--high);
    }
</style>
