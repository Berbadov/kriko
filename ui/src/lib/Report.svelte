<script lang="ts">
    import { api } from "./api";
    import ClaimCard from "./ClaimCard.svelte";
    import type { Mode } from "./mode";
    import {
        absenceNote,
        asMarkdown,
        claimKey,
        contextLines,
        groupByDomain,
        severityWord,
    } from "./report";
    import { hashWith, route } from "./router";
    import type { LookupResult } from "./types";
    import Verdict from "./Verdict.svelte";

    let {
        result,
        mode = "buyer",
        lookupId = "",
        heading = "",
    }: {
        result: LookupResult;
        mode?: Mode;
        lookupId?: string;
        heading?: string;
    } = $props();

    const groups = $derived(groupByDomain(result.claims));
    const context = $derived(contextLines(result.context, result.context_units));

    let handled = $state<string[]>([]);
    let notes = $state<Record<string, string>>({});

    // Triage is per stored answer, so an unsaved result simply has none. The
    // component renders identically either way rather than growing a second
    // read-only variant. Both halves arrive in one request: a report that
    // paints its checkboxes and then, a beat later, its notes reads as two
    // pages loading.
    $effect(() => {
        if (!lookupId) return;
        api.triage(lookupId)
            .then((t) => {
                handled = t.checked ?? [];
                notes = t.notes ?? {};
            })
            .catch(() => {});
    });

    async function check(key: string, next: boolean) {
        handled = next ? [...handled, key] : handled.filter((k) => k !== key);
        if (!lookupId) return;
        try {
            handled = (await api.setChecked(lookupId, key, next)).checked ?? handled;
        } catch {
            // The optimistic update above stands. A failed note is not worth
            // yanking a checkbox back out from under the reader's cursor.
        }
    }

    async function saveNote(key: string, text: string) {
        notes = { ...notes, [key]: text };
        if (!lookupId) return;
        try {
            notes = (await api.setNote(lookupId, key, text)).notes ?? notes;
        } catch {
            // Same tolerance as the checkbox: their sentence stays on screen.
        }
    }

    // Handing the report to someone who does not have Kriko. Clipboard first
    // because the destination is a message; the textarea is the fallback,
    // since a webview can refuse clipboard access and a button that silently
    // does nothing is the bug this whole session started from.
    let copied = $state("");
    let fallback = $state("");

    async function handOver() {
        const text = asMarkdown(result, { heading, notes, handled });
        try {
            await navigator.clipboard.writeText(text);
            copied = "Copied as Markdown.";
            fallback = "";
        } catch {
            copied = "";
            fallback = text;
        }
    }
</script>

<header class="report-head">
    {#if heading}<h2>{heading}</h2>{/if}
    <Verdict {result} {handled} {mode} />

    <!-- What the answer was computed against. The reader's first question
         about a short report is whether it even had the usage figure, and
         the payload has always carried the answer. -->
    {#if context.length}
        <p class="context-strip">
            <span class="meta">Answered for</span>
            {#each context as pair (pair.key)}
                <span class="context-pair"
                    ><span class="meta">{pair.key}</span> {pair.value}</span
                >
            {/each}
        </p>
    {/if}

    <div class="row no-print">
        {#if lookupId}
            <a
                class="button-like"
                href={hashWith({ mode: $route.query.mode, id: lookupId }, "questions")}
                >Question sheet</a
            >
        {/if}
        <button class="ghost" onclick={() => window.print()}>Print / Save as PDF</button>
        <button class="ghost" onclick={handOver}>Copy for a mechanic</button>
        {#if lookupId}
            <a
                class="ghost button-like"
                href={hashWith({ mode: $route.query.mode, left: lookupId }, "compare")}
                >Compare with another</a
            >
        {/if}
    </div>
    {#if copied}<p class="meta no-print">{copied}</p>{/if}
    {#if fallback}
        <label class="no-print handover">
            <span class="meta"
                >This browser would not take it to the clipboard — select and copy:</span
            >
            <textarea readonly rows="6" value={fallback}></textarea>
        </label>
    {/if}
</header>

<!-- No empty-state paragraph here: the verdict above already renders
     emptyReason(), and printing the same sentence twice was the shape the
     old header had before it carried a verdict at all. -->
{#if result.claims.length}
    <div class="report-body">
        {#each groups as group (group.domain)}
            <section class="group">
                <h3 class="group-head">
                    {group.domain}
                    <!-- The worst thing in this section, in the peripheral
                         vision. Scanning a long report by heading is how a
                         reader decides which section to read first. -->
                    <span class="sev {group.claims[0].severity}"
                        >{severityWord(group.claims[0].severity)}</span
                    >
                    <span class="meta">{group.claims.length}</span>
                </h3>
                {#each group.claims as claim (claimKey(claim))}
                    <ClaimCard
                        {claim}
                        {mode}
                        checked={handled.includes(claimKey(claim))}
                        note={notes[claimKey(claim)] ?? ""}
                        onCheck={(next) => check(claimKey(claim), next)}
                        onNote={(text) => saveNote(claimKey(claim), text)}
                    />
                {/each}
            </section>
        {/each}
    </div>
{/if}

<!-- What a short report does *not* mean. The coverage lens answers this for
     an author; a reader looking at three claims has the same question and no
     screen for it, and leaving it implied is the one thing this project
     cannot afford to do.
     Only when there *are* claims: on an empty answer the verdict above has
     already said which kind of empty it is, and saying it twice on one screen
     reads as two different findings. -->
{#if result.claims.length}
    <details class="absence">
        <summary class="meta">Why might this be short?</summary>
        <p class="meta">{absenceNote(result)}</p>
    </details>
{/if}
