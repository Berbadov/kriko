<script lang="ts">
    import { api } from "./api";
    import { copyText } from "./clipboard";
    import ClaimCard from "./ClaimCard.svelte";
    import type { Mode } from "./mode";
    import {
        absenceNote,
        asMarkdown,
        canCheckFacts,
        claimKey,
        contextLines,
        groupByDomain,
        severityWord,
    } from "./report";
    import { hashWith, route } from "./router";
    import type { FactCheck, LookupResult } from "./types";
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

    /* What the cited pages say now.
     *
     * Read once for the whole report rather than per card: forty claims is
     * forty requests to be told "not checked yet", and the answers are
     * already stored. Keyed by pack *and* claim, because a claim id is only
     * unique inside its pack.
     *
     * A failure is silence. This is a supplementary badge on a report that is
     * complete without it, and a red banner over someone's answer because a
     * status table could not be read would be the tail wagging the dog.
     */
    let facts = $state<Record<string, FactCheck>>({});
    let checking = $state<Record<string, boolean>>({});
    const factKey = (claim: { pack_id?: string; claim_id?: string }) =>
        `${claim.pack_id ?? ""}\u0000${claim.claim_id ?? ""}`;

    $effect(() => {
        api.factChecks()
            .then((payload) => {
                const next: Record<string, FactCheck> = {};
                for (const item of payload.items ?? []) next[factKey(item)] = item;
                facts = next;
            })
            .catch(() => {});
    });

    async function checkFacts(claim: (typeof result.claims)[number]) {
        const key = factKey(claim);
        checking = { ...checking, [key]: true };
        try {
            facts = { ...facts, [key]: await api.checkFacts(claim.pack_id!, claim.claim_id!) };
        } catch {
            // Same tolerance as the read above: the claim and its sources are
            // on screen, and the reader can open the link themselves — which
            // is what they had to do before this button existed.
        } finally {
            checking = { ...checking, [key]: false };
        }
    }

    /* One press for the whole report.
     *
     * Sequential on purpose. Firing forty fetches at forty domains at once
     * from a reader's own address is a burst that looks like a scraper to
     * every one of them, and the app has no business doing that on their
     * behalf. `stop` is read between claims so leaving the screen ends it —
     * the effect above is what re-reads the results on the way back.
     */
    let sweeping = $state(false);
    let swept = $state(0);
    let stop = false;
    $effect(() => () => {
        stop = true;
    });

    async function checkEverything() {
        const targets = result.claims.filter(canCheckFacts);
        sweeping = true;
        swept = 0;
        for (const claim of targets) {
            if (stop) break;
            await checkFacts(claim);
            swept += 1;
        }
        sweeping = false;
    }

    // Handing the report to someone who does not have Kriko. Clipboard first
    // because the destination is a message; the textarea is the fallback,
    // since a webview can refuse clipboard access and a button that silently
    // does nothing is the bug this whole session started from.
    let copied = $state("");
    let fallback = $state("");

    async function handOver() {
        const text = asMarkdown(result, { heading, notes, handled });
        const ok = await copyText(text);
        copied = ok ? "Copied as Markdown." : "";
        fallback = ok ? "" : text;
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
        <!-- Above Print, because it changes what gets printed. -->
        {#if result.claims.some(canCheckFacts)}
            <button class="ghost" disabled={sweeping} onclick={checkEverything}>
                {sweeping
                    ? `Reading the sources… ${swept} of ${result.claims.filter(canCheckFacts).length}`
                    : "Check every source"}
            </button>
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
                        factCheck={facts[factKey(claim)] ?? null}
                        checkingFacts={checking[factKey(claim)] ?? false}
                        onCheckFacts={() => checkFacts(claim)}
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

<!-- B113 phase 3. The browser panel legitimately shows two blocks this screen
     cannot — both read off the reader's own listing page, and neither ever
     sent to the engine, because the engine has no schema for them and
     acquiring one would be a category-shaped thing inside a core that must
     stay generic.

     That is the right design, and it is also invisible: a reader comparing the
     two surfaces sees the panel showing more and reasonably concludes one of
     them is broken. So the rule is the answer here, not the symptom. -->
<details class="absence">
    <summary class="meta">Does the browser panel show more than this?</summary>
    <p class="meta">
        On a listing page it does, deliberately. The panel also draws what it
        reads from that page itself — the seller's own condition and equipment
        blocks — which never reaches Kriko's store and so cannot appear here.
        Everything on this screen is what is <em>known</em> about the product:
        that is the part which travels between installations, and the part a
        pack can be held to.
    </p>
</details>
