<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import Async from "../lib/Async.svelte";
    import PageHead from "../lib/kriko/PageHead.svelte";
    import Key from "../lib/kriko/Key.svelte";
    import Board from "../lib/Board.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { compareMany, compareSpecs } from "../lib/compare";
    import { severityWord } from "../lib/report";
    import { route, setQuery, toHash } from "../lib/router";
    import { ApiError } from "../lib/api";
    import { remedyFor } from "../lib/failure";
    import { follow } from "../lib/jobs";
    import type {
        CompareDraft,
        CompareQuestion,
        HistoryItem,
        SubjectDetail,
    } from "../lib/types";

    //: Four is the cap, and it is a layout limit rather than a logical one:
    //: `compareMany` takes any number, but a fifth column stops fitting the
    //: measure and a shortlist longer than four is not a shortlist.
    const MAX = 4;

    let items = $state<HistoryItem[]>([]);
    let drafts = $state<CompareDraft[]>([]);

    // The ids live in the URL so a comparison stays a link someone can paste,
    // the same reason mode does. `left`/`right` are still read because every
    // Report page links here with `?left=`, and a link that stops working is
    // a worse cost than carrying two spellings.
    // `params[0]` is the extension's spelling: `/api/focus` refuses a query
    // string, so a route posted from the panel can only carry an id as a path
    // segment. It seeds the first column and leaves the rest to be picked,
    // which is exactly what "compare this one with something" means.
    const ids = $derived(
        ($route.query.ids
            ? $route.query.ids.split(",")
            : [
                  $route.query.left ?? $route.params[0] ?? "",
                  $route.query.right ?? "",
              ]
        )
            .map((id) => id.trim())
            .filter(Boolean)
            .filter((id, i, all) => all.indexOf(id) === i)
            .slice(0, MAX),
    );

    // Always at least two, and one trailing empty slot beyond what is chosen:
    // two because a comparison screen showing one picker does not read as a
    // comparison, and the trailing one so adding a third is a visible act
    // rather than a feature the reader has to be told about.
    const slots = $derived(
        ids.length < MAX ? [...ids, ...Array(Math.max(1, 2 - ids.length)).fill("")] : ids,
    );

    function choose(index: number, value: string) {
        const next = [...ids];
        if (value) next[index] = value;
        else next.splice(index, 1);
        setQuery("ids", next.filter(Boolean).join(",") || undefined);
    }

    // A draft is the same ids under a name (B183). Which one is open rides in
    // the URL beside them, so a saved comparison is still a link.
    const draftId = $derived($route.query.draft ?? "");
    const open = $derived(drafts.find((d) => d.draft_id === draftId));
    let name = $state("");
    let saving = $state(false);
    let saveError = $state("");
    $effect(() => {
        name = open?.name ?? "";
    });

    // Fails open: a comparison works without its drafts, so a list that will
    // not load is an empty one rather than a broken screen.
    const loadDrafts = () =>
        api
            .compareDrafts()
            .then((r) => (drafts = r.items))
            .catch(() => {});
    loadDrafts();

    function openDraft(d: CompareDraft) {
        setQuery("draft", d.draft_id);
        setQuery("ids", d.lookup_ids.join(",") || undefined);
    }

    function newDraft() {
        setQuery("draft", undefined);
        setQuery("ids", undefined);
    }

    async function save() {
        saving = true;
        saveError = "";
        try {
            const saved = await api.saveCompareDraft(name, ids, open?.draft_id ?? "");
            await loadDrafts();
            setQuery("draft", saved.draft_id);
        } catch (e) {
            saveError = remedyFor(e).headline;
        } finally {
            saving = false;
        }
    }

    async function remove() {
        if (!open) return;
        await api.deleteCompareDraft(open.draft_id).catch(() => {});
        await loadDrafts();
        setQuery("draft", undefined);
    }

    let missingNotice = $state("");

    const listed = api.history(50).then((h) => (items = h.items));

    // A compare link can arrive by hash change rather than a fresh mount
    // (the extension's /api/focus hand-off does exactly this), so `items`
    // — read once at mount — falls behind the ids the table is about to show
    // (check-19). Refetch whenever an id the URL names is not one we have.
    $effect(() => {
        if (ids.some((id) => !items.some((i) => i.lookup_id === id))) {
            api.history(50).then((h) => (items = h.items));
        }
    });

    // A check's specifications are its subject's own attributes. The first
    // subject the lookup matched is the product; a subject that cannot be read
    // leaves its column empty rather than failing the comparison.
    const subjectOf = (id: string | undefined): Promise<SubjectDetail | null> =>
        id ? api.subject(id).catch(() => null) : Promise.resolve(null);

    const lined = $derived(
        ids.length >= 2
            ? Promise.allSettled(ids.map((id) => api.getLookup(id))).then(async (settled) => {
                  const answers: Awaited<ReturnType<typeof api.getLookup>>[] = [];
                  const remaining: string[] = [];
                  let dropped = false;
                  settled.forEach((r, i) => {
                      if (r.status === "fulfilled") {
                          answers.push(r.value);
                          remaining.push(ids[i]);
                      } else if (r.reason instanceof ApiError && r.reason.status === 404) {
                          dropped = true;
                      } else {
                          throw r.reason;
                      }
                  });
                  if (dropped) {
                      missingNotice = "One saved check was forgotten and was removed.";
                      setQuery("ids", remaining.join(",") || undefined);
                  }
                  const subjects = await Promise.all(
                      answers.map((a) => subjectOf(a.response.subjects?.[0])),
                  );
                  return {
                      answers,
                      diff: compareMany(answers),
                      specs: compareSpecs(subjects),
                  };
              })
            : null,
    );

    // Details open on demand and one at a time (B183): a section of the table
    // and, inside it, one row. Until the reader chooses, the section holding
    // the most to read is open, and nothing inside it is.
    let chosenSection = $state<"specs" | "risks" | "">("");
    let detail = $state("");
    const toggleSection = (id: "specs" | "risks", current: string) => {
        chosenSection = current === id ? "" : id;
        detail = "";
    };
    const toggleDetail = (key: string) => (detail = detail === key ? "" : key);

    // Notes (B193): the same per-claim note the Report page holds, editable
    // from the comparison, because "belt done at 90k per this seller" is
    // written while deciding, not while reading one report. One store, one
    // key: the note written here shows on the Report page and vice versa.
    // Loaded per side, only when a detail row is opened — a table the reader
    // is scanning should not cost a triage request per column.
    let triage = $state<Record<string, Record<string, string>>>({});
    let noteDrafts = $state<Record<string, string>>({});
    let noteBusy = $state("");

    async function loadTriage(lookupId: string) {
        if (triage[lookupId]) return;
        try {
            const t = await api.triage(lookupId);
            triage = { ...triage, [lookupId]: t.notes ?? {} };
        } catch {
            triage = { ...triage, [lookupId]: {} };
        }
    }

    async function saveNote(lookupId: string, claimKey: string, text: string) {
        noteBusy = `${lookupId}:${claimKey}`;
        const next = { ...(triage[lookupId] ?? {}), [claimKey]: text };
        triage = { ...triage, [lookupId]: next };
        try {
            const t = await api.setNote(lookupId, claimKey, text);
            triage = { ...triage, [lookupId]: t.notes ?? next };
        } catch {
            // Their sentence stays on screen; the Report page behaves the
            // same way on the same failure.
        } finally {
            noteBusy = "";
        }
    }

    const cellNote = (lookupId: string | undefined, key: string) =>
        lookupId ? (triage[lookupId] ?? {})[key] ?? "" : "";

    // Follow-up questions (B193): the question the table raises, asked of
    // the reader's own agent with the table attached. Only a saved draft can
    // be asked about — a question is part of the comparison the reader named
    // and kept, not of whatever is temporarily picked.
    let questions = $state<CompareQuestion[]>([]);
    let questionDraft = $state("");
    let asking = $state("");
    let askError = $state("");

    $effect(() => {
        const id = draftId;
        questions = [];
        if (id) {
            api.compareQuestions(id)
                .then((r) => (questions = r.items ?? []))
                .catch(() => {});
        }
    });

    // The board (B194): the reader's free marks over the table. It rides in
    // the URL beside the ids so a board session is a link like every other
    // state on this screen, and it needs a saved draft: marks belong to a
    // named comparison, not to whatever is temporarily picked.
    const boarding = $derived($route.query.board === "1" && !!open);
    const toggleBoard = () => setQuery("board", boarding ? undefined : "1");

    // The first glance (B194): each side's serious count, said before any
    // section is opened. Derived from the lined-up answers only, so no
    // category word is needed to say it.
    const serious = (claims: { severity?: string }[]) =>
        claims.filter((c) => c.severity === "high" || c.severity === "critical").length;

    // The chosen sides' own labels, for the one suggestion that names two
    // of them. From history (already loaded), not another fetch.
    const chosenLabels = $derived(
        ids.map((id) => items.find((i) => i.lookup_id === id)?.label ?? ""),
    );

    // Suggested questions (B194): pressed straight from the diff the reader
    // is looking at, one press fills the box. The words name no category
    // and no product; they are about counts and columns.
    const suggestions = (labels: string[]) => [
        "Which of these has the fewest serious risks?",
        "Which one is the cheapest to fix, and why?",
        "What is the single biggest difference between them?",
        labels.length >= 2
            ? `Between ${labels[0]} and ${labels[1]}, which would you buy and why?`
            : "",
    ].filter(Boolean);

    async function ask() {
        const text = questionDraft.trim();
        if (!open || !text || asking) return;
        asking = "starting";
        askError = "";
        try {
            const started = await api.askCompareQuestion(
                open.draft_id, text);
            asking = started.job_id;
            questionDraft = "";
            follow(started.job_id, (job) => {
                if (job.done) {
                    asking = "";
                    void api.compareQuestions(open!.draft_id)
                        .then((r) => (questions = r.items ?? []))
                        .catch(() => {});
                }
            });
        } catch (thrown) {
            asking = "";
            askError = remedyFor(thrown).headline;
        }
    }
</script>

<PageHead crumb="check / compare" title="Compare" lead="Products side by side: the specifications and the known risks, cell by cell." />
<div class="k-spread" style="margin-bottom: 24px">
    <span class="k-note">Data only. Nothing here rates a product.</span>
    {#if open}
        <Key variant="plate" pressed={boarding} onclick={toggleBoard}>Board</Key>
    {/if}
</div>

<Async promise={listed} loading="Loading history…">
    {#snippet children()}
        {#if items.length < 2}
            <EmptyState
                title="Compare needs two saved checks"
                detail="Check each of the ones you are weighing up from the browser extension
                        and they will all be here, up to four at a time."
                actionLabel="Browser extension"
                actionHref={toHash("extension")}
            />
        {:else}
            <h3><Icon name="history" size={18} /> Drafts</h3>
            <div class="k-row" style="margin-bottom: 12px">
                {#each drafts as d (d.draft_id)}
                    <button
                        type="button"
                        class:primary={d.draft_id === draftId}
                        aria-pressed={d.draft_id === draftId}
                        onclick={() => openDraft(d)}>{d.name}</button
                    >
                {/each}
                <Key variant="ghost" onclick={newDraft}>New</Key>
            </div>
            <div class="k-row" style="margin-bottom: 12px">
                <div class="field grow">
                    <label for="draft-name">Draft name</label>
                    <input id="draft-name" bind:value={name} maxlength="80" />
                </div>
                <button
                    type="button"
                    disabled={saving || !name.trim() || ids.length < 2}
                    onclick={save}>{open ? "Update" : "Save"}</button
                >
                {#if open}<button type="button" onclick={remove}>Delete</button>{/if}
            </div>
            {#if saveError}<p class="state" role="alert">{saveError}</p>{/if}

            <div class="row slots">
                {#each slots as id, index (index)}
                    <div class="field">
                        <label for="slot-{index}">
                            {index === 0 ? "First" : index === 1 ? "Second" : `#${index + 1}`}
                        </label>
                        <select
                            id="slot-{index}"
                            value={id}
                            onchange={(e) => choose(index, e.currentTarget.value)}
                        >
                            <option value="">{index < 2 ? "choose…" : "add another…"}</option>
                            {#each items as item (item.lookup_id)}
                                <option
                                    value={item.lookup_id}
                                    disabled={item.lookup_id !== id &&
                                        ids.includes(item.lookup_id)}>{item.label}</option
                                >
                            {/each}
                        </select>
                    </div>
                {/each}
            </div>

            {#if missingNotice}<p class="state">{missingNotice}</p>{/if}
            {#if lined}
                <Async promise={lined} loading="Loading the answers…">
                    {#snippet children(d)}
                        {@const width = d.answers.length}
                        {@const section =
                            chosenSection || (d.specs.length ? "specs" : "risks")}
                        {#if boarding}
                            <div class="board-wrap">
                                <Board
                                    draftId={open!.draft_id}
                                    onClose={toggleBoard}
                                />
                            </div>
                        {/if}
                        <p class="lede-compare">
                            {d.diff.shared}{width === 2
                                ? " in both"
                                : ` in all ${width}`} · {d.diff.only
                                .map(
                                    (n: number, i: number) =>
                                        `${n} only in ${d.answers[i].label}`,
                                )
                                .join(" · ")}
                        </p>
                        <p class="lede-compare">
                            {#each d.answers as answer (answer.lookup_id)}
                                {#if answer.lookup_id !== d.answers[0].lookup_id}<span class="meta"> · </span>{/if}{answer.label}:
                                {@const n = serious(answer.response.claims)}
                                {n === 0
                                    ? "no serious risk recorded"
                                    : `${n} serious${n === 1 ? "" : "s"}`}
                            {/each}
                        </p>
                        <div class="table-scroll">
                            <table class="compare k-table">
                                <thead>
                                    <tr>
                                        <th scope="col">Product</th>
                                        {#each d.answers as answer (answer.lookup_id)}
                                            <th scope="col">{answer.label}</th>
                                        {/each}
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr class="group">
                                        <th scope="rowgroup" colspan={width + 1}>
                                            <button
                                                type="button"
                                                aria-expanded={section === "specs"}
                                                onclick={() => toggleSection("specs", section)}
                                            >
                                                <Icon name="tag" size={16} /> Specifications
                                                <span class="meta">{d.specs.length}</span>
                                            </button>
                                        </th>
                                    </tr>
                                    {#if section === "specs"}
                                        {#each d.specs as row (row.label)}
                                            <tr class:differs={row.differs}>
                                                <th scope="row">
                                                    <button
                                                        type="button"
                                                       
                                                        aria-expanded={detail === `s:${row.label}`}
                                                        onclick={() => toggleDetail(`s:${row.label}`)}
                                                        >{row.label}</button
                                                    >
                                                </th>
                                                {#each row.cells as cell, i (i)}
                                                    <td>
                                                        {#if cell}{cell.value}{:else}<span class="meta"
                                                                >Not recorded</span
                                                            >{/if}
                                                    </td>
                                                {/each}
                                            </tr>
                                            {#if detail === `s:${row.label}`}
                                                <tr class="detail">
                                                    <td></td>
                                                    {#each row.cells as cell, i (i)}
                                                        <td>
                                                            {#if cell?.source}
                                                                <a
                                                                    href={cell.source}
                                                                    target="_blank"
                                                                    rel="noreferrer">Source</a
                                                                >
                                                            {:else}<span class="meta">No source</span>{/if}
                                                        </td>
                                                    {/each}
                                                </tr>
                                            {/if}
                                        {:else}
                                            <tr>
                                                <td colspan={width + 1} class="meta"
                                                    >No specifications recorded.</td
                                                >
                                            </tr>
                                        {/each}
                                    {/if}
                                    <tr class="group">
                                        <th scope="rowgroup" colspan={width + 1}>
                                            <button
                                                type="button"
                                                aria-expanded={section === "risks"}
                                                onclick={() => toggleSection("risks", section)}
                                            >
                                                <Icon name="warn" size={16} /> Known risks
                                                <span class="meta">{d.diff.rows.length}</span>
                                            </button>
                                        </th>
                                    </tr>
                                    {#if section === "risks"}
                                        {#each d.diff.rows as row (row.key)}
                                            <tr>
                                                <th scope="row">
                                                    <button
                                                        type="button"
                                                       
                                                        aria-expanded={detail === `r:${row.key}`}
                                                        onclick={() => toggleDetail(`r:${row.key}`)}
                                                        >{row.title}</button
                                                    >
                                                </th>
                                                {#each row.cells as cell, i (i)}
                                                    <td>
                                                        {#if cell}
                                                            <span class="sev {cell.severity}"
                                                                >{severityWord(cell.severity)}</span
                                                            >
                                                        {:else}<span
                                                                class="meta"
                                                                title="No installed catalog holds this risk for this product"
                                                                >None</span
                                                            >{/if}
                                                    </td>
                                                {/each}
                                            </tr>
                                            {#if detail === `r:${row.key}`}
                                                <tr class="detail">
                                                    <td></td>
                                                    {#each row.cells as cell, i (i)}
                                                        <td>
                                                            {#if cell}
                                                                {cell.body}
                                                                {#if cell.advice}<em>{cell.advice}</em>{/if}
                                                                {#each cell.sources ?? [] as s (s.url ?? s.domain)}
                                                                    <a
                                                                        href={s.url ?? "#"}
                                                                        target="_blank"
                                                                        rel="noreferrer"
                                                                        >{s.domain ?? "Source"}</a
                                                                    >
                                                                {/each}
                                                                <label class="note-field">
                                                                    <span class="meta"
                                                                        >Your note on this risk</span
                                                                    >
                                                                    <textarea
                                                                        rows="2"
                                                                        value={cellNote(d.answers[i].lookup_id, row.key)}
                                                                        onfocus={() => loadTriage(d.answers[i].lookup_id)}
                                                                        onblur={(e) =>
                                                                            saveNote(
                                                                                d.answers[i].lookup_id,
                                                                                row.key,
                                                                                e.currentTarget.value,
                                                                            )}
                                                                        placeholder="e.g. seller says the belt was done at 90k"
                                                                    ></textarea>
                                                                </label>
                                                            {/if}
                                                        </td>
                                                    {/each}
                                                </tr>
                                            {/if}
                                        {/each}
                                    {/if}
                                </tbody>
                            </table>
                        </div>
                    {/snippet}
                </Async>
                {#if open}
                    <section class="questions" aria-label="Follow-up questions">
                        <h3><Icon name="questions" size={18} /> Ask your agent</h3>
                        <p class="meta">
                            A question about this shortlist, answered by an agent with
                            the table above attached. Kept with the draft, so reopening
                            the comparison reopens the conversation.
                        </p>
                        <div class="row">
                            <div class="field grow">
                                <label for="compare-question">Question</label>
                                <input
                                    id="compare-question"
                                    bind:value={questionDraft}
                                    maxlength="2000"
                                    placeholder="e.g. which of these is cheaper to fix?"
                                    onkeydown={(e) => e.key === "Enter" && ask()}
                                />
                            </div>
                            <button
                                type="button"
                                disabled={asking !== "" || !questionDraft.trim()}
                                onclick={ask}
                            >{asking ? "Asking…" : "Ask"}</button>
                        </div>
                        <div class="row suggestions">
                            {#each suggestions(chosenLabels) as text (text)}
                                <button
                                    type="button"
                                    class="ghost"
                                    disabled={asking !== ""}
                                    onclick={() => (questionDraft = text)}
                                >{text}</button>
                            {/each}
                        </div>
                        {#if askError}<p class="state" role="alert">{askError}</p>{/if}
                        {#if asking && asking !== "starting"}
                            <p class="state">Your agent is answering; Activity keeps the run.</p>
                        {/if}
                        {#each questions as q (q.question_id)}
                            <article class="card question">
                                <h4>{q.question}</h4>
                                {#if q.answer}
                                    <p class="answer">{q.answer}</p>
                                {:else if q.job_id === asking}
                                    <p class="meta">Asking your agent…</p>
                                {:else}
                                    <p class="meta">Asked; no answer was recorded.</p>
                                {/if}
                                {#if q.job_id}
                                    <p class="meta">
                                        <a href={toHash("activity")}>The run's log</a>
                                    </p>
                                {/if}
                            </article>
                        {/each}
                    </section>
                {:else if ids.length >= 2}
                    <p class="meta">
                        Save this comparison as a draft to ask your agent a question
                        about it.
                    </p>
                {/if}
            {:else}
                <p class="meta">Pick at least two different saved checks to line them up.</p>
            {/if}
        {/if}
    {/snippet}
</Async>

<style>
    h2 button {
        margin-left: var(--s-3);
        vertical-align: middle;
    }

    .board-wrap {
        margin: var(--s-3) 0;
    }

    .suggestions {
        margin: var(--s-2) 0;
    }

    .note-field {
        display: block;
        margin-top: var(--s-2);
    }

    .questions {
        margin-top: var(--s-4);
    }

    .questions h3 {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }

    .question h4 {
        margin: 0 0 var(--s-2);
    }

    .question .answer {
        white-space: pre-wrap;
        line-height: var(--lh-read);
    }
</style>
