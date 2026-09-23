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

    let prefs = $state<Promise<Prefs>>(api.prefs());
    let saved = $state("");
    let failure = $state<unknown>(null);

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

<article class="card">
    <h3><Icon name="agents" /> Your agents</h3>
    <p class="meta">
        Every coding-agent command line found on this machine, with the two dials
        that decide what one run costs. Left alone, each uses the CLI's own default,
        so an installation that never opens this panel behaves exactly as it did.
    </p>

    {#if failure}<Failure error={failure} />{/if}

    <Async promise={prefs} loading="Reading your choices…">
        {#snippet children(data)}
            {#if harnessesOf(data).length}
                <div class="field">
                    <label for="p-harness">Preferred agent</label>
                    <select
                        id="p-harness"
                        value={data.chosen?.preferred_harness ?? ''}
                        onchange={(event) =>
                            save({ preferred_harness: event.currentTarget.value })}
                    >
                        <option value="">Whichever is installed</option>
                        {#each harnessesOf(data) as one (one.id)}
                            <option value={one.id}>{one.label}</option>
                        {/each}
                    </select>
                    <p class="meta">
                        Which one Kriko starts when a run does not name one.
                    </p>
                </div>

                <div class="agentgrid">
                    {#each harnessesOf(data) as one (one.id)}
                        <section class="agentcard">
                            <div class="agenthead">
                                <Icon name="agent" size={20} />
                                <strong>{one.label}</strong>
                                {#if data.chosen?.preferred_harness === one.id}
                                    <span class="badge" title="what a run uses unless told otherwise"
                                        >preferred</span
                                    >
                                {/if}
                            </div>
                            <p class="meta mono">{one.path || one.command}</p>
                            {#if one.needs_account}
                                <p class="meta">
                                    <Icon name="cost" size={14} /> Bills to {one.needs_account}.
                                </p>
                            {/if}

                            {#if one.llm_selectable}
                                <label class="field">
                                    <span class="dial"><Icon name="llm" size={15} /> LLM</span>
                                    <Pick
                                        value={one.llm ?? ""}
                                        options={(one.llms ?? []).map((name) => ({ value: name }))}
                                        emptyLabel="CLI default"
                                        hint={one.llm_hint}
                                        onpick={(chosen) =>
                                            save({ [key("harness_model", one.id)]: chosen })}
                                    />
                                </label>
                                <p class="meta">
                                    {#if (one.llms ?? []).length}
                                        These are the names this CLI itself reported.
                                        "Something else…" sends whatever you type straight
                                        through — the CLI judges the name, not Kriko.
                                    {:else}
                                        This CLI named nothing, so there is nothing to list.
                                        Pick "Something else…" and type {one.llm_hint
                                            || "a name it accepts"}.
                                    {/if}
                                </p>
                            {:else}
                                <p class="meta">
                                    <Icon name="llm" size={14} />
                                    Runs its own LLM — Kriko has no verified per-run switch
                                    for this CLI yet.
                                </p>
                            {/if}

                            <!-- The second dial, and the cheap one. Dropping a
                                 survey run from high to low costs a fraction of
                                 what switching the LLM does and changes nothing
                                 about which account pays — so it belongs in the
                                 same card, not a screen away.

                                 Drawn only where this machine's CLI declares the
                                 flag in its own --help: a control whose every
                                 choice fails on argument parsing is worse than
                                 no control. -->
                            {#if (one.efforts ?? []).length}
                                <label class="field">
                                    <span class="dial"><Icon name="effort" size={15} /> Effort</span>
                                    <Pick
                                        value={one.effort ?? ""}
                                        options={(one.efforts ?? []).map((name) => ({ value: name }))}
                                        emptyLabel="CLI default"
                                        hint={one.effort_hint}
                                        onpick={(chosen) =>
                                            save({ [key("harness_effort", one.id)]: chosen })}
                                    />
                                </label>
                                <p class="meta">
                                    How hard it thinks, per run. Lower is cheaper and faster;
                                    this CLI names {(one.efforts ?? []).join(", ")}.
                                </p>
                            {/if}
                        </section>
                    {/each}
                </div>
            {:else}
                <p class="state empty">
                    No coding-agent CLI was found on this machine. The harness plane is
                    what runs research at no marginal cost, so this is worth fixing
                    before the paid one.
                </p>
            {/if}

            <!-- Not found, each with the way out. A missing CLI is the
                 ordinary state, not an error, and it is listed even when
                 others were found: "detected harnesses aren't including the
                 all" was a real report, and the first thing that screen owed
                 the reader was the list of what it had looked for. -->
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

            <!-- Installed, found, and skipped on purpose. Left unsaid, this
                 reads as Kriko failing to notice a tool the reader can see on
                 their own PATH. -->
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
    h3 {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }
    .field {
        margin-block: 0.9rem;
    }
    /* One box per agent, and they wrap. The grid is what makes the two dials
       legible: a pick inside a bordered box with a name on it belongs to that
       name, which a flat column of labels never managed to say. */
    .agentgrid {
        display: grid;
        gap: var(--s-3);
        grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr));
        margin-block: var(--s-3);
    }
    .agentcard {
        padding: var(--s-3);
        border: 1px solid var(--line);
        border-radius: var(--radius);
    }
    .agenthead {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
        margin-bottom: var(--s-2);
    }
    /* The icon sits on the label rather than beside the control, so the two
       dials read as a pair down the card's left edge. */
    .dial {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }
    .mono {
        font-family: var(--mono, monospace);
        overflow-wrap: anywhere;
    }
    .klabel {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }
</style>
