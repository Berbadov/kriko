<script lang="ts">
    /* The sheet you take to the seller.
     *
     * The product principle is "the configuration- and usage-specific risks a buyer
     * cannot cheaply get from the standard inspection — before they book the
     * expert". The artifact that principle implies is a list of *questions*,
     * and until now `askLine(claim)` was readable one card at a time and
     * nowhere as a whole.
     *
     * Two modes, same data. The list is for reading at a desk and for paper.
     * Focus mode is for standing on a forecourt holding a phone: one question,
     * large, with the answer field and nothing else on screen. Both write to
     * the same two tables the report writes to, so a note left here is on the
     * card there. */
    import Icon from "../lib/Icon.svelte";
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { questions, severityWord, type Question } from "../lib/report";
    import { hashWith, route } from "../lib/router";
    import type { StoredLookup } from "../lib/types";

    let { lookupId = "" }: { lookupId?: string } = $props();

    let stored = $state<StoredLookup | null>(null);
    let list = $state<Question[]>([]);
    let handled = $state<string[]>([]);
    let notes = $state<Record<string, string>>({});

    /** No id in the link resolves to the newest saved answer.
     *
     * Deliberate: on inspection day the reader opens this from the rail, not
     * from a report, and "the check I just ran" is what they mean every time.
     * A screen that demanded an id here would send them back through History
     * to fetch one. */
    async function load() {
        let id = lookupId;
        if (!id) {
            const recent = await api.history(1);
            id = recent.items[0]?.lookup_id ?? "";
        }
        if (!id) return;
        stored = await api.getLookup(id);
        list = questions(stored.response);
        const triage = await api.triage(id);
        handled = triage.checked ?? [];
        notes = triage.notes ?? {};
    }

    const ready = load();

    const id = $derived(stored?.lookup_id ?? "");
    const done = $derived(new Set(handled));
    const answered = $derived(list.filter((q) => done.has(q.key)).length);

    let focus = $state(false);
    let at = $state(0);
    const current = $derived(list[Math.min(at, Math.max(0, list.length - 1))]);

    async function check(key: string, next: boolean) {
        handled = next ? [...handled, key] : handled.filter((k) => k !== key);
        if (!id) return;
        try {
            handled = (await api.setChecked(id, key, next)).checked ?? handled;
        } catch {
            // Their tick stays. See Report.svelte for the same tolerance.
        }
    }

    async function note(key: string, text: string) {
        notes = { ...notes, [key]: text };
        if (!id) return;
        try {
            notes = (await api.setNote(id, key, text)).notes ?? notes;
        } catch {
            // ditto
        }
    }

    /** Next unanswered, not next in the list.
     *
     * Focus mode exists to be worked through, and stepping onto a question
     * already ticked is the reader doing the app's bookkeeping for it. */
    function advance(step: number) {
        if (!list.length) return;
        for (let i = 1; i <= list.length; i += 1) {
            const index = (at + step * i + list.length * list.length) % list.length;
            if (!done.has(list[index].key)) {
                at = index;
                return;
            }
        }
        at = (at + step + list.length) % list.length;
    }
</script>

<Async promise={ready} loading="Loading the sheet…">
    {#snippet children()}
        {#if !stored}
            <EmptyState
                title="No saved check to build a sheet from"
                detail="A question sheet is built from an answer you already have — the
                        questions are the per-claim advice, worst first. Run a check and
                        this fills itself in."
                actionLabel="Run a check"
                actionHref={hashWith({ mode: $route.query.mode }, "check")}
            />
        {:else if !list.length}
            <EmptyState
                title="Nothing to ask about {stored.label}"
                detail="The installed packs hold no claims for this one, so there are no
                        questions to put to the seller. That is a coverage gap, not a
                        clean bill of health."
                actionLabel="See the report"
                actionHref={hashWith({ mode: $route.query.mode }, "result", stored.lookup_id)}
            />
        {:else}
            <header class="sheet-head">
                <h2><Icon name="questions" size={22} /> Questions for {stored.label}</h2>
                <p class="meta">
                    {answered} of {list.length} answered · worst first · every one of
                    these is specific to this one, not general advice
                </p>
                <div class="row no-print">
                    <button
                        class="ghost"
                        aria-pressed={focus}
                        onclick={() => (focus = !focus)}
                    >
                        {focus ? "Show the whole list" : "One at a time"}
                    </button>
                    <button class="ghost" onclick={() => window.print()}
                        >Print / Save as PDF</button
                    >
                    <a
                        class="ghost button-like"
                        href={hashWith(
                            { mode: $route.query.mode },
                            "result",
                            stored.lookup_id,
                        )}>Full report</a
                    >
                </div>
            </header>

            {#if focus}
                <!-- Inspection day. Large type, one question, the answer field,
                     and the two controls a thumb can reach. -->
                <section class="focus-card" class:done={done.has(current.key)}>
                    <p class="meta">
                        {severityWord(current.severity)} · {current.domain} · {at + 1}
                        of {list.length}
                    </p>
                    <p class="focus-ask">{current.ask}</p>
                    <p class="meta">{current.title}</p>
                    <textarea
                        rows="3"
                        placeholder="What did they say?"
                        value={notes[current.key] ?? ""}
                        onblur={(e) => note(current.key, e.currentTarget.value)}
                    ></textarea>
                    <div class="row">
                        <button class="ghost" onclick={() => advance(-1)}>Back</button>
                        <button
                            onclick={() => {
                                check(current.key, !done.has(current.key));
                                advance(1);
                            }}
                            >{done.has(current.key) ? "Un-tick" : "Asked"}</button
                        >
                        <button class="ghost" onclick={() => advance(1)}>Skip</button>
                    </div>
                </section>
            {:else}
                <ol class="sheet">
                    {#each list as question (question.key)}
                        <li class:done={done.has(question.key)}>
                            <label class="check">
                                <input
                                    type="checkbox"
                                    checked={done.has(question.key)}
                                    onchange={(e) =>
                                        check(question.key, e.currentTarget.checked)}
                                />
                                <span class="sev {question.severity}"
                                    >{severityWord(question.severity)}</span
                                >
                                <span class="sheet-ask">{question.ask}</span>
                            </label>
                            <p class="meta">{question.title}</p>
                            <textarea
                                rows="1"
                                placeholder="What did they say?"
                                value={notes[question.key] ?? ""}
                                onblur={(e) => note(question.key, e.currentTarget.value)}
                            ></textarea>
                        </li>
                    {/each}
                </ol>
            {/if}
        {/if}
    {/snippet}
</Async>
