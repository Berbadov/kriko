<script lang="ts">
    import Icon from "./Icon.svelte";
    import { api } from "./api";
    import { demandWord, kindTone, kindWord, promptFor, rowName } from "./agenda";
    import type { Agenda, AgendaRow } from "./types";

    /* What to research next, on the screen where an agent gets wired up.
     *
     * Here rather than on a rail entry of its own because it answers the
     * question the reader already has on this screen: is connecting this
     * thing worth it, and what will it do first? These are the same rows
     * `research_agenda` hands the agent, so what is on the screen is what
     * will actually be picked — the ordering is visible before it is acted
     * on, which is the whole reason a demand-ranked list is trustworthy.
     *
     * Every row also copies as a prompt, for the harness this app cannot
     * reach. Pasting a sentence into a chat window is the lowest common
     * denominator of every agent that exists, and it makes this screen
     * useful before any config has been written.
     */
    let data = $state<Agenda | null>(null);
    let failed = $state(false);
    let copied = $state("");

    // Tolerant on purpose: an agenda is a head start, not a prerequisite. A
    // screen that could not compute one must still connect a harness.
    api.agenda()
        .then((payload) => (data = payload))
        .catch(() => (failed = true));

    const rows = $derived(data?.rows ?? []);

    const keyOf = (row: AgendaRow): string =>
        `${row.kind} ${row.subject_id} ${row.claim_id ?? ""} ${row.identity ?? ""}`;

    async function copy(row: AgendaRow) {
        try {
            await navigator.clipboard.writeText(promptFor(row));
            copied = keyOf(row);
        } catch {
            copied = ""; // a denied clipboard is not an error worth a banner
        }
    }
</script>

<article class="card">
    <h3><Icon name="agenda" /> What to research next</h3>
    {#if failed}
        <p class="meta">
            The ordering could not be worked out. Connecting a harness still works — an
            agent can ask for the agenda itself.
        </p>
    {:else if rows.length}
        <p class="meta">
            Ranked by what this installation was actually asked about, over the last
            {data?.window} analyses. An agent gets these same rows from
            <code>research_agenda</code>.
        </p>
        <ul class="agenda">
            {#each rows as row (keyOf(row))}
                <li>
                    <div class="agenda-head">
                        <span class="badge" class:fact-warn={kindTone(row.kind) === "warn"}
                            >{kindWord(row.kind)}</span
                        >
                        <strong>{rowName(row)}</strong>
                        {#if demandWord(row)}
                            <span class="meta">{demandWord(row)}</span>
                        {/if}
                    </div>
                    <p class="meta">{row.why}</p>
                    <button class="link-ish" onclick={() => copy(row)}>
                        {copied === keyOf(row) ? "Copied" : "Copy as a prompt"}
                    </button>
                </li>
            {/each}
        </ul>
        {#if data?.note}
            <!-- A worse ordering, said out loud. Silence here would let a
                 fresh install's alphabetical list read as a considered one. -->
            <p class="meta">{data.note}</p>
        {/if}
    {:else}
        <p class="meta">
            Nothing to research: every subject the enabled packs carry already holds
            claims.{data?.note ? ` ${data.note}` : ""}
        </p>
    {/if}
</article>
