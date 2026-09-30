<script lang="ts">
    import Async from "./Async.svelte";
    import Pick from "./Pick.svelte";
    import Icon from "./Icon.svelte";
    import Failure from "./Failure.svelte";
    import { api } from "./api";
    import type { Prefs } from "./types";

    /* Which agent drives, and what it drives with — one card per agent.
     *
     * This was a run of eight `.field` divs inside one box: a dropdown, then
     * every installed CLI's LLM picker, then every installed CLI's effort
     * picker, then a search provider, then an LLM, then a catalogue. The
     * reader's words were "they look all separate", and they were reading it
     * correctly: nothing on screen said which control belonged to which
     * agent, because nothing grouped them. A card per agent is the whole
     * fix — the two dials that decide what one agent costs sit inside the
     * box with that agent's name on it.
     *
     * The paid plane's own choices (search provider, completion LLM, the
     * catalogue) stayed behind in `Planes.prefs.svelte`. They are a
     * different decision with a different bill, and putting them in the same
     * undivided column as "which CLI" is most of why this screen read as a
     * pile.
     *
     * One word is deliberately absent here, in prose and in labels: the one
     * a pack uses as an identity key. `test_ui_contains_no_pack_vocabulary`
     * holds the client to naming none, and "LLM" says the same thing in the
     * engine's vocabulary rather than in a category's.
     */

    /** Bumped by the parent whenever a key changes elsewhere on the page
     * (settings-4) — the harness list itself does not depend on keys, but
     * `needs_account` framing and the models a CLI reports can, and a reader
     * who just saved a key should not need a reload to see it reflected. */
    let { keysVersion = 0, onReask = () => {} }: {
        keysVersion?: number;
        onReask?: () => void;
    } = $props();

    let prefs = $state<Promise<Prefs>>(api.prefs());
    let saved = $state("");
    let failure = $state<unknown>(null);

    let seenKeysVersion = 0;
    $effect(() => {
        if (keysVersion === seenKeysVersion) return;
        seenKeysVersion = keysVersion;
        prefs = api.prefs();
    });

    async function save(values: Record<string, string>) {
        failure = null;
        try {
            prefs = Promise.resolve(await api.savePrefs(values));
            saved = "Saved.";
            setTimeout(() => (saved = ""), 2500);
        } catch (thrown) {
            failure = thrown;
        }
    }

    // After signing in to a CLI or updating it. Each CLI's list is cached for
    // ten minutes on the server, because asking costs a process start per CLI.
    let asking = $state(false);
    let reasked = $state("");
    async function reask() {
        asking = true;
        failure = null;
        reasked = "";
        try {
            const data = await api.prefs(true);
            prefs = Promise.resolve(data);
            const listed = harnessesOf(data).filter((one) => (one.llms ?? []).length).length;
            reasked = `Asked ${harnessesOf(data).length} CLIs — ${listed} listed LLMs`;
            // The "Which LLM, which search" panel above pulls from the same
            // /api/prefs and does not otherwise know this happened.
            onReask();
        } catch (thrown) {
            failure = thrown;
        } finally {
            asking = false;
        }
    }

    // Every read of the payload is defended. Not defensive habit: this panel
    // renders whatever `/api/prefs` answered, and an older engine — or a
    // browser that reconnected mid-upgrade — answers with fewer fields than
    // this build knows about. A screen that throws on a missing key takes
    // the whole page with it.
    const harnessesOf = (data: Prefs) => data?.harnesses ?? [];
    const unusableOf = (data: Prefs) => data?.unusable ?? [];
    const missingOf = (data: Prefs) => data?.missing ?? [];

    // The preference key is the id with its dashes folded, which is what the
    // server reads. Written once here rather than inline twice, because the
    // two picks below would otherwise each carry their own copy of the rule.
    const key = (prefix: string, id: string) => `${prefix}_${id.replace(/-/g, "_")}`;
</script>

<!-- B146: "agent and settings section are very crowded and ugly". This was
     a 19rem card per agent, each holding a path, two dials and two paragraphs
     of help — three screens for four agents. It is one row per agent now: the
     name and the two dials on one line, the help said once underneath. -->
<article class="card">
    <div class="head">
        <h3><Icon name="agents" /> Your agents</h3>
        <button class="ghost small" disabled={asking} onclick={reask}>
            {asking ? "Asking the CLIs…" : "Re-ask the CLIs for their LLMs"}
        </button>
    </div>

    {#if failure}<Failure error={failure} />{/if}

    <Async promise={prefs} loading="Reading your choices…">
        {#snippet children(data)}
            {#if harnessesOf(data).length}
                <label class="preferred">
                    <span>Preferred agent</span>
                    <select
                        id="p-harness"
                        value={data.chosen?.preferred_harness ?? ""}
                        onchange={(event) =>
                            save({ preferred_harness: event.currentTarget.value })}
                    >
                        <option value="">Whichever is installed</option>
                        {#each harnessesOf(data) as one (one.id)}
                            <option value={one.id}>{one.label}</option>
                        {/each}
                    </select>
                    <span class="meta">used when a run does not name one</span>
                </label>
                {#if reasked}<p class="state" role="status">{reasked}</p>{/if}

                <ul class="agents">
                    {#each harnessesOf(data) as one (one.id)}
                        <li class="agentrow">
                            <div class="who">
                                <strong>
                                    <Icon name="agent" size={16} />
                                    {one.label}
                                    {#if data.chosen?.preferred_harness === one.id}
                                        <span class="badge">preferred</span>
                                    {/if}
                                </strong>
                                <span class="meta mono" title={one.path || one.command}
                                    >{one.path || one.command}</span
                                >
                                {#if one.needs_account}
                                    <span class="meta">Bills to {one.needs_account}.</span>
                                {/if}
                            </div>
                            <div class="dialbox">
                                <span class="dial"><Icon name="llm" size={14} /> LLM</span>
                                {#if one.llm_selectable}
                                    <Pick
                                        value={one.llm ?? ""}
                                        options={(one.llms ?? []).map((name) => ({ value: name }))}
                                        emptyLabel="CLI default"
                                        hint={one.llm_hint}
                                        note={one.llms_note}
                                        onpick={(chosen) =>
                                            save({ [key("harness_model", one.id)]: chosen })}
                                    />
                                {:else}
                                    <span class="meta fixed">its own — no per-run switch</span>
                                {/if}
                            </div>
                            <!-- Drawn only where this machine's CLI declares the
                                 flag in its own --help: a control whose every
                                 choice fails on argument parsing is worse than
                                 no control. -->
                            <div class="dialbox">
                                <span class="dial"><Icon name="effort" size={14} /> Effort</span>
                                {#if (one.efforts ?? []).length}
                                    <Pick
                                        value={one.effort ?? ""}
                                        options={(one.efforts ?? []).map((name) => ({ value: name }))}
                                        emptyLabel="CLI default"
                                        hint={one.effort_hint}
                                        onpick={(chosen) =>
                                            save({ [key("harness_effort", one.id)]: chosen })}
                                    />
                                {:else}
                                    <span class="meta fixed">not offered by this CLI</span>
                                {/if}
                            </div>
                        </li>
                    {/each}
                </ul>
                <p class="meta legend">
                    Lists are what each CLI reported itself; "Something else…" passes any
                    name straight through. Lower effort answers sooner and costs less.
                    Left on "CLI default", each behaves exactly as it does in a terminal.
                </p>
            {:else}
                <p class="state empty">
                    No coding-agent CLI was found on this machine. The harness plane is
                    what runs research at no marginal cost, so this is worth fixing
                    before the paid one.
                </p>
            {/if}

            <!-- Not found, each with the way out. A missing CLI is the
                 ordinary state, not an error, and it is listed even when
                 others were found. -->
            {#if missingOf(data).length}
                <details>
                    <summary>
                        {missingOf(data).length} more Kriko knows how to drive, not installed here
                    </summary>
                    <ul class="klist">
                        {#each missingOf(data) as one (one.id)}
                            <li class="krow">
                                <div class="kmain">
                                    <span class="klabel">
                                        <Icon name="download" size={15} />
                                        {one.label}
                                        {#if one.download_url}
                                            <a href={one.download_url} target="_blank" rel="noreferrer">docs</a>
                                        {/if}
                                    </span>
                                    {#if one.install_hint}<code>{one.install_hint}</code>{/if}
                                    {#if one.needs_account}
                                        <span class="meta">{one.needs_account}.</span>
                                    {/if}
                                </div>
                            </li>
                        {/each}
                    </ul>
                    {#if data?.dirs_env}
                        <p class="meta">
                            Installed somewhere unusual? Set <code>{data.dirs_env}</code> to its
                            folder and reload — Kriko searches PATH, that variable, then the
                            usual install folders.
                        </p>
                    {/if}
                </details>
            {/if}

            {#each unusableOf(data) as one (one.id)}
                <p class="meta">
                    <Icon name="warn" size={14} />
                    <strong>{one.label}</strong> is installed and not used: {one.why}
                </p>
            {/each}

            {#if saved}<p class="state"><Icon name="ok" size={14} /> {saved}</p>{/if}
        {/snippet}
    </Async>
</article>

<style>
    .head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
    h3,
    .who strong {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        margin: 0;
    }
    .preferred {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--s-2);
        margin-block: var(--s-3);
    }
    .preferred > span:first-child {
        font-weight: 600;
    }
    .agents {
        list-style: none;
        margin: 0;
        padding: 0;
        border-top: 1px solid var(--line);
    }
    /* Name, LLM, effort — one line per agent at desktop width, stacking only
       when the window is too narrow for three columns. */
    .agentrow {
        display: grid;
        grid-template-columns: minmax(12rem, 1.4fr) minmax(9rem, 1fr) minmax(9rem, 1fr);
        gap: var(--s-2) var(--s-3);
        align-items: start;
        padding-block: var(--s-2);
        border-bottom: 1px solid var(--line);
    }
    @media (max-width: 760px) {
        .agentrow {
            grid-template-columns: 1fr 1fr;
        }
        .who {
            grid-column: 1 / -1;
        }
    }
    .who {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        min-width: 0;
    }
    .dialbox {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        min-width: 0;
    }
    .dial {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.8rem;
        color: var(--ink-2);
    }
    .fixed {
        padding-block: 0.4rem;
    }
    .mono {
        font-family: var(--font-mono);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .legend {
        margin-block: var(--s-2) var(--s-3);
        max-width: var(--measure);
    }
    .klabel {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }
</style>
