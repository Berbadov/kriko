<script lang="ts">
    import Async from "./Async.svelte";
    import Pick from "./Pick.svelte";
    import Icon from "./Icon.svelte";
    import Failure from "./Failure.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import type { AgentTarget, Prefs } from "./types";

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
            reasked = `Asked ${harnessesOf(data).length} CLIs; ${listed} listed LLMs`;
            // The "Which LLM, which search" panel above pulls from the same
            // /api/prefs and does not otherwise know this happened.
            onReask();
        } catch (thrown) {
            failure = thrown;
        } finally {
            asking = false;
        }
    }

    // Connection state, one MCP config per target. A row in this list is an
    // agent; the target with the same id is how Kriko reaches it, so the state
    // and the one action sit on that row (B164, D7) and not in a section of
    // their own. A client that has no CLI here (Cursor, VS Code) still gets a
    // row below the others, so its Connect did not disappear with the section.
    let targets = $state<AgentTarget[]>([]);
    let busy = $state("");
    // The exception per row, never a string: the sentence is derived from the
    // status (B72), and one config someone broke by hand must not hide the
    // rows that are fine.
    let rowError = $state<Record<string, unknown>>({});

    async function loadTargets() {
        try {
            targets = (await api.agentTargets()).targets;
        } catch (thrown) {
            failure = thrown;
        }
    }
    loadTargets();

    const targetOf = (id: string) => targets.find((one) => one.id === id);
    const apartOf = (data: Prefs) =>
        targets.filter((one) => !harnessesOf(data).some((agent) => agent.id === one.id));

    const WORDS: Record<string, string> = {
        connected: "Connected",
        stale: "Points elsewhere",
        absent: "Not connected",
        unreadable: "Config unreadable",
    };

    // One action per row. Whether the *protocol* on disk is current is a
    // different question from whether the agent is wired: it is generated from
    // the catalogs and from this app's code, so a wired agent can carry an old
    // one. Connect writes both, which is why only a wired agent is offered the
    // skill alone.
    function actionOf(target: AgentTarget): "Connect" | "Rewrite" | "Update skill" | null {
        if (target.state === "unreadable") return null;
        if (target.state !== "connected") return "Connect";
        return target.skill?.present && target.skill.stale ? "Update skill" : "Rewrite";
    }

    async function act(target: AgentTarget) {
        busy = target.id;
        rowError = { ...rowError, [target.id]: null };
        try {
            if (actionOf(target) === "Update skill") await api.refreshAgentSkill(target.id);
            else await api.connectAgent(target.id);
            await loadTargets();
        } catch (thrown) {
            rowError = { ...rowError, [target.id]: thrown };
        } finally {
            busy = "";
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
    // The Local row's LLM is the local plane's own setting
    // (`prefs.harness_model_key`), so one choice holds on every screen.
    const key = (prefix: string, id: string) =>
        prefix === "harness_model" && id === "local" ? "local_model" : `${prefix}_${id.replace(/-/g, "_")}`;

    // The mark (D2). A vendor's own logo is a trademark, and the app carries
    // none until the reader supplies the published assets; until then each
    // agent is a monogram of its name, drawn from the label the CLI list
    // already gives, so a new CLI needs no entry here.
    const markOf = (label: string) => (label.trim()[0] ?? "?").toUpperCase();
</script>

{#snippet connection(target: AgentTarget)}
    {@const action = actionOf(target)}
    <div class="conn">
        <span class="badge state-{target.state}">{WORDS[target.state]}</span>
        {#if action}
            <button class="small" disabled={busy === target.id} onclick={() => act(target)}>
                {action}
            </button>
        {/if}
        {#if target.detail}<span class="meta">{target.detail}</span>{/if}
        {#if rowError[target.id]}
            <span class="state error">{remedyFor(rowError[target.id]).headline}</span>
        {/if}
    </div>
{/snippet}

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
                </label>
                {#if reasked}<p class="state" role="status">{reasked}</p>{/if}

                <ul class="agents">
                    {#each harnessesOf(data) as one (one.id)}
                        <li class="agentrow">
                            <!-- B177: one row is a mark, a state, an LLM, an effort
                                 and one action. The path and the billing account
                                 moved into the tooltip: they are facts to look up,
                                 not text to read on every visit. -->
                            <div
                                class="who"
                                title={[one.path || one.command, one.needs_account ? `Bills to ${one.needs_account}` : ""]
                                    .filter(Boolean)
                                    .join(" · ")}
                            >
                                <strong>
                                    <span class="mark" aria-hidden="true">{markOf(one.label)}</span>
                                    {one.label}
                                    {#if data.chosen?.preferred_harness === one.id}
                                        <span class="badge">preferred</span>
                                    {/if}
                                </strong>
                            </div>
                            {#if targetOf(one.id)}
                                {@render connection(targetOf(one.id)!)}
                            {/if}
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
                                    <span class="meta fixed">its own; no per-run switch</span>
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
                    {#each apartOf(data) as target (target.id)}
                        <li class="agentrow apart">
                            <div class="who">
                                <strong>
                                    <span class="mark" aria-hidden="true">{markOf(target.label)}</span>
                                    {target.label}
                                </strong>
                                <span class="meta mono" title={target.path}>{target.path}</span>
                            </div>
                            {@render connection(target)}
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="state empty">No coding agent was found on this machine.</p>
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
                            folder and reload; Kriko searches PATH, that variable, then the
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
        grid-template-columns: minmax(12rem, 1.4fr) minmax(10rem, 1fr) minmax(9rem, 1fr) minmax(9rem, 1fr);
        gap: var(--s-2) var(--s-3);
        align-items: start;
        padding-block: var(--s-2);
        border-bottom: 1px solid var(--line);
    }
    .apart :global(.conn) {
        grid-column: 2 / -1;
    }
    .conn {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--s-2);
        min-width: 0;
    }
    .state-connected {
        background: var(--low-soft);
        color: var(--low);
    }
    .state-stale,
    .state-unreadable {
        background: var(--high-soft);
        color: var(--high);
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
    .mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.4rem;
        height: 1.4rem;
        border: 1px solid var(--line);
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 700;
        flex: none;
    }
    .klabel {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }
</style>
