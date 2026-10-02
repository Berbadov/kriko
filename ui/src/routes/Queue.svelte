<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { follow, isLive, stateWord } from "../lib/jobs";
    import { doing } from "../lib/live";
    import { count } from "../lib/plural";
    import { hashWith, toHash } from "../lib/router";
    import type { Job, Subject } from "../lib/types";
import PageHead from "../lib/kriko/PageHead.svelte";

    /* Research several products, one after another (B193).
     *
     * The reader picks the subjects first, here, rather than reaching each
     * one through Browse. Picking is a search plus a row: the same
     * `/api/subjects` Browse reads, so no new endpoint and no vocabulary
     * of the catalogs' own words enters the source.
     *
     * The queue itself is the existing jobs worker, not a new one: one
     * `POST /api/research` per subject, submitted in the order picked, and
     * the worker that already runs everything runs them one at a time.
     * So there is no batch job to invent, and each run keeps its own undo
     * through Activity. A subject that fails to submit names itself and
     * never stops the rest.
     */
    const SEARCH_MS = 250;

    let query = $state("");
    let results = $state<Subject[]>([]);
    let searching = $state(false);

    // The picked subjects, in the order they were picked: the queue's order.
    let picked = $state<Subject[]>([]);

    // One row per submitted subject, in the same order as the picks.
    let rows = $state<Row[]>([]);
    let error = $state<unknown>(null);
    let busy = $state(false);

    type Row = { subject: Subject; job?: Job; failure?: string };

    const stops = new Map<string, () => void>();
    let now = $state(Date.now());

    let searchClock: ReturnType<typeof setTimeout> | undefined;
    $effect(() => {
        if (searchClock) clearTimeout(searchClock);
        if (!query.trim()) {
            results = [];
            searching = false;
            return;
        }
        searching = true;
        searchClock = setTimeout(async () => {
            try {
                const found = await api.subjects(query.trim(), 25);
                // Picked subjects stay picked, never search results twice.
                results = found.filter(
                    (one) => !picked.some((p) => p.subject_id === one.subject_id),
                );
            } catch {
                results = [];
            } finally {
                searching = false;
            }
        }, SEARCH_MS);
        return () => searchClock && clearTimeout(searchClock);
    });

    $effect(() => {
        const clock = setInterval(() => (now = Date.now()), 1000);
        return () => {
            clearInterval(clock);
            stops.forEach((stop) => stop());
            stops.clear();
        };
    });

    const isPicked = (id: string) => picked.some((p) => p.subject_id === id);

    function add(subject: Subject) {
        if (isPicked(subject.subject_id)) return;
        picked = [...picked, subject];
        query = "";
        results = [];
    }

    function drop(id: string) {
        picked = picked.filter((p) => p.subject_id !== id);
        rows = rows.filter((row) => row.subject.subject_id !== id);
    }

    async function submit() {
        if (!picked.length || busy) return;
        busy = true;
        error = null;
        const pending = picked;
        rows = [...rows, ...pending.map((subject) => ({ subject }))];
        picked = [];
        try {
            for (const subject of pending) {
                const { job_id } = await api.research({
                    subject_id: subject.subject_id,
                    pack_id: subject.pack_id,
                });
                const job = await api.job(job_id);
                at(subject.subject_id, (row) => (row.job = job));
                watch(job_id, subject.subject_id);
            }
        } catch (cause) {
            error = cause;
        } finally {
            busy = false;
        }
    }

    function at(id: string, change: (row: Row) => void) {
        rows = rows.map((row) => {
            if (row.subject.subject_id !== id) return row;
            const next = { ...row };
            change(next);
            return next;
        });
    }

    function watch(jobId: string, subjectId: string) {
        if (stops.has(subjectId)) return;
        stops.set(
            subjectId,
            follow(jobId, (job) => at(subjectId, (row) => (row.job = job))),
        );
    }

    const finished = $derived(
        rows.length > 0 && rows.every((row) => row.job && !isLive(row.job)),
    );
</script>

<PageHead crumb="check / queue" title="Queue" lead="Pick several products first; research runs one after another." />

<div class="card">
    <label class="field grow">
        <span>Products</span>
        <input
            bind:value={query}
            placeholder="search the installed catalogs"
            autocomplete="off"
        />
    </label>
    {#if searching}
        <p class="meta">Searching…</p>
    {:else if results.length}
        <ul class="picks">
            {#each results as subject (subject.subject_id)}
                <li>
                    <button class="ghost" onclick={() => add(subject)}>
                        <Icon name="plus" size={14} />
                        {subject.label}
                    </button>
                    <span class="meta">{count(subject.claims, "claim")}</span>
                </li>
            {/each}
        </ul>
    {/if}

    {#if picked.length}
        <ol class="chosen">
            {#each picked as subject (subject.subject_id)}
                <li>
                    <span>{subject.label}</span>
                    <button
                        class="ghost"
                        onclick={() => drop(subject.subject_id)}
                        aria-label="Remove {subject.label}"
                    >
                        Remove
                    </button>
                </li>
            {/each}
        </ol>
        <button class="primary" onclick={submit} disabled={busy}>
            {busy ? "Queueing" : `Queue ${count(picked.length, "product")}`}
        </button>
    {/if}
</div>

{#if error}
    <Failure {error} retry={submit} />
{/if}

{#if rows.length}
    <div class="stage" role="region" aria-label="Queued research">
        {#if finished}
            <p class="meta" role="status">
                <Icon name="ok" size={14} /> The queue has finished.
                <a href={hashWith({ lens: "runs" }, "activity")}>Activity → Runs</a>
            </p>
        {/if}
        {#each rows as row (row.subject.subject_id)}
            <div class="row" class:live={row.job ? isLive(row.job) : true}>
                <div class="main">
                    <a
                        class="label"
                        href={toHash("knowledge", row.subject.subject_id)}
                    >{row.subject.label}</a>
                    <span class="meta">
                        {#if row.job}
                            {stateWord(row.job)}{isLive(row.job) ? ` · ${doing(row.job)}` : ""}
                        {:else}
                            waiting its turn
                        {/if}
                    </span>
                </div>
            </div>
        {/each}
    </div>
{:else if !picked.length}
    <EmptyState
        title="Nothing is queued"
        detail="Search for the products you are interested in, then queue them for research."
        actionLabel="Open Browse"
        actionHref={toHash("knowledge")}
    />
{/if}

<style>
    .card {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        margin-block-end: var(--s-4);
    }
    .grow {
        display: block;
    }
    .picks,
    .chosen {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
    }
    .picks li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-2);
    }
    .chosen li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-2);
    }
    .stage {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .row {
        background: var(--n-0);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: var(--s-2) var(--s-3);
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
    }
    .label {
        font-weight: var(--w-strong, 600);
    }
</style>
