<script lang="ts">
    import Async from "./Async.svelte";
    import Failure from "./Failure.svelte";
    import HarnessLlm from "./HarnessLlm.svelte";
    import { api } from "./api";
    import type { Costs, Prefs } from "./types";

    /* Which agent, which LLM, which search provider — and what it costs.
     *
     * All three existed as facts rather than decisions: the harness plane took
     * the first CLI it found, the paid plane took whatever LLM_MODEL said, and
     * search meant Exa because Exa was the only provider with code. Each is a
     * fine default and a poor rule.
     *
     * One word is deliberately absent from this file, in prose and in labels:
     * the one a pack uses as an identity key. `test_ui_contains_no_pack_
     * vocabulary` holds the client to naming none, and "LLM" says the same
     * thing in the engine's vocabulary rather than in a category's — which the
     * API already does, calling the provenance field `llm`.
     *
     * Costs sit in the same panel deliberately. At the moment of choosing a
     * plane, "which" and "what will it cost" are one decision, and a
     * preference a reader sets without being shown the bill is how a surprise
     * happens.
     */

    let prefs = $state<Promise<Prefs>>(api.prefs());
    let costs = $state<Promise<Costs>>(api.costs());
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

    // After signing in to a CLI or updating it: its list is cached for ten
    // minutes, because asking costs a process start per CLI.
    let asking = $state(false);
    async function reask() {
        asking = true;
        failure = null;
        try {
            prefs = Promise.resolve(await api.prefs(true));
        } catch (thrown) {
            failure = thrown;
        } finally {
            asking = false;
        }
    }

    // Typed out of the payload rather than inline: `Async`'s snippet hands
    // the body an `unknown`, and a cast at the point of use would be a cast
    // per row instead of one per screen.
    const estimates = (data: Costs) => Object.values(data?.estimates ?? {});

    // Every read of the payload is defended. Not defensive habit: this panel
    // renders whatever `/api/prefs` answered, and an older engine — or a
    // browser that reconnected mid-upgrade — answers with fewer fields than
    // this build knows about. A screen that throws on a missing key takes the
    // whole Settings page with it.
    const harnessesOf = (data: Prefs) => data?.harnesses ?? [];
    const unusableOf = (data: Prefs) => data?.unusable ?? [];
    const searchersOf = (data: Prefs) => data?.search_providers ?? [];
    const offeredOf = (data: Prefs) => data?.models?.offered ?? [];
    // The reason beside the name, because "why can I not pick Opus" has an
    // answer and a bare id withholds it.
    const paidLabel = (data: Prefs, id: string) => {
        const one = offeredOf(data).find((row) => row.id === id);
        return one ? `${one.label}${one.unusable ? ` — ${one.unusable}` : ""}` : id;
    };
    const spentOf = (data: Costs) => data?.spent?.planes ?? [];

    const money = (usd: number | null | undefined) =>
        usd === null || usd === undefined ? "not measured" : `$${usd.toFixed(4)}`;
</script>

<section>
    <h3>Which agent, which LLM, which search</h3>
    <p class="meta">
        Every one of these falls back to what this machine offers when it is left
        empty, so an installation that never opens this panel behaves exactly as it
        did.
    </p>

    {#if failure}<Failure error={failure} />{/if}

    <Async promise={prefs} loading="Reading your choices…">
        {#snippet children(data)}
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
                {#if !harnessesOf(data).length}
                    <p class="meta">
                        No coding-agent CLI was found on this machine. The harness plane
                        is what runs research at no marginal cost, so this is worth
                        fixing before the paid one.
                    </p>
                    {#each data?.missing ?? [] as one (one.id)}
                        <p class="meta">
                            <strong>{one.label}</strong>
                            {#if one.download_url}
                                — <a href={one.download_url} target="_blank" rel="noreferrer">download</a>
                            {/if}
                            {#if one.install_hint}<br /><code>{one.install_hint}</code>{/if}
                            {#if one.needs_account}<br />{one.needs_account}.{/if}
                        </p>
                    {/each}
                    {#if data?.dirs_env}
                        <p class="meta">
                            Installed somewhere unusual? Set <code>{data.dirs_env}</code> to its
                            folder and reload this panel — Kriko searches PATH, that variable,
                            then the usual install folders.
                        </p>
                    {/if}
                {/if}
                {#each unusableOf(data) as one (one.id)}
                    <p class="meta">{one.label} is installed and not used: {one.why}</p>
                {/each}
            </div>

            {#if harnessesOf(data).length}
                <div class="llms" role="group" aria-labelledby="p-llms-head">
                    <div class="llms-head">
                        <span id="p-llms-head" class="label">Each agent's LLM</span>
                        <span class="meta">as that agent's own CLI names them</span>
                        {#if harnessesOf(data).some((one) => one.llm_selectable)}
                            <button class="ghost small" disabled={asking} onclick={reask}>
                                {asking ? "Asking…" : "Re-ask the CLIs"}
                            </button>
                        {/if}
                    </div>
                    {#each harnessesOf(data) as one (one.id)}
                        <label for={`p-llm-${one.id}`}>{one.label}</label>
                        {#if one.llm_selectable}
                            <HarnessLlm
                                id={`p-llm-${one.id}`}
                                label={`${one.label} LLM`}
                                llms={one.llms ?? []}
                                value={one.llm ?? ""}
                                hint={one.llm_hint}
                                onchange={(value) =>
                                    save({
                                        [`harness_model_${one.id.replace(/-/g, "_")}`]: value,
                                    })}
                            />
                            <span class="meta">
                                {#if (one.llms ?? []).length}
                                    {(one.llms ?? []).length} offered
                                {:else}
                                    none listed — Other… takes {one.llm_hint || "any name"}
                                {/if}
                            </span>
                        {:else}
                            <span class="meta wide-cell">
                                runs its own default — no verified per-run switch yet
                            </span>
                        {/if}
                    {/each}
                </div>
            {/if}

            <div class="field">
                <label for="p-search">Search provider</label>
                <select
                    id="p-search"
                    value={data.chosen?.search_provider ?? ''}
                    onchange={(event) =>
                        save({ search_provider: event.currentTarget.value })}
                >
                    <option value="">Whichever has a key</option>
                    {#each searchersOf(data) as one (one.id)}
                        <option value={one.id} disabled={!one.ready}
                            >{one.label}{one.ready ? "" : " — no key set"}</option
                        >
                    {/each}
                </select>
                <p class="meta">
                    Which engine reads the web for a paid run. It decides what the
                    LLM ever sees, so it sits upstream of every other setting here.
                </p>
            </div>

            <div class="field">
                <label for="p-llm">Paid-plane LLM</label>
                <HarnessLlm
                    id="p-llm"
                    label="Paid-plane LLM"
                    llms={offeredOf(data).map((one) => one.id)}
                    labelOf={(id) => paidLabel(data, id)}
                    value={data.chosen?.llm_model ?? ""}
                    defaultLabel={`Default (${data.models?.default ?? "the endpoint's"})`}
                    hint="any name your completion endpoint accepts"
                    onchange={(value) => save({ llm_model: value })}
                />
                <p class="meta">
                    {data.models?.note ?? ''} Currently: <code>{data.models?.current ?? '—'}</code>.
                </p>
            </div>
            <datalist id="p-llms">
                {#each data.models?.offered ?? [] as one (one.id)}
                    <option value={one.id}>{one.label} — {one.unusable || one.provider}</option>
                {/each}
            </datalist>
            {#if data.effective}
                <p class="meta">Paid extraction uses <code>{data.effective.llm}</code> with {data.effective.search || 'no search provider'}.</p>
                {#if data.effective.reason}<p class="state">{data.effective.reason}</p>{/if}
                {#if data.effective.harness_note}<p class="meta">{data.effective.harness_note}</p>{/if}
            {/if}
            <details>
                <summary>LLM catalogue and stage preferences</summary>
                <p class="meta">Custom IDs are accepted. Prices are USD per million tokens; unknown is not free. Edit prices in <code>{data.models?.catalogue ?? 'your catalogue'}</code>.</p>
                <table>
                    <thead><tr><th>LLM</th><th>Context</th><th>Input / output</th><th>Speed</th><th>Availability</th></tr></thead>
                    <tbody>
                        {#each data.models?.offered ?? [] as one (one.id)}
                            <tr><th>{one.label}</th><td>{one.context?.toLocaleString() ?? 'unknown'}</td><td>{one.usd_in ?? 'unknown'} / {one.usd_out ?? 'unknown'}</td><td>{one.speed || 'unknown'}</td><td>{one.unusable || 'key configured'}</td></tr>
                        {/each}
                    </tbody>
                </table>
                {#each data.roles ?? [] as role (role.id)}
                    <label class="field">
                        {role.id} — {role.note}
                        <input list="p-llms" value={role.chosen} disabled={!role.active} placeholder={data.models?.current ?? ''} onchange={(event) => save({ [`llm_model_${role.id}`]: event.currentTarget.value })} />
                    </label>
                    <p class="meta">{role.active ? `Uses ${role.effective}; a per-run choice wins.` : role.inactive_reason}</p>
                {/each}
            </details>
            {#if saved}<p class="state">{saved}</p>{/if}
        {/snippet}
    </Async>
</section>

<section>
    <h3>What it has cost</h3>
    <Async promise={costs} loading="Adding it up…">
        {#snippet children(data)}
            <ul class="strip" aria-label="Spend">
                <li>
                    <strong>{money(data.spent?.usd)}</strong>
                    <span class="meta">in {data.spent?.days ?? 30} days</span>
                </li>
                <li>
                    <strong>{(data.spent?.tokens ?? 0).toLocaleString()}</strong>
                    <span class="meta">tokens</span>
                </li>
                <li>
                    <strong>{data.spent?.runs ?? 0}</strong>
                    <span class="meta">run(s)</span>
                </li>
            </ul>

            {#if spentOf(data).length}
                <ul class="klist" aria-label="By plane">
                    {#each spentOf(data) as row (row.plane + row.llm)}
                        <li class="krow">
                            <div class="kmain">
                                <span class="klabel">{row.plane} · {row.llm || "—"}</span>
                                <span class="meta">
                                    {row.runs} run(s), {row.priced} of them priced
                                </span>
                            </div>
                            <span class="meta">
                                {money(row.usd)}
                                {#if row.usd_per_run !== null}
                                    · {money(row.usd_per_run)} each
                                {/if}
                            </span>
                        </li>
                    {/each}
                </ul>
            {/if}

            <h4>What the next one is likely to cost</h4>
            <ul class="klist" aria-label="Estimates">
                {#each estimates(data) as row (row.plane)}
                    <li class="krow">
                        <div class="kmain">
                            <span class="klabel">{row.plane}</span>
                            <span class="meta">{row.note}</span>
                        </div>
                        <span class="meta">{money(row.usd)}</span>
                    </li>
                {/each}
            </ul>

            <p class="meta">{data.balance?.note ?? ''}</p>
        {/snippet}
    </Async>
</section>

<style>
    .field {
        margin-block: 0.9rem;
    }
    .field :global(select) {
        align-self: flex-start;
    }
    .llms {
        display: grid;
        grid-template-columns: max-content max-content 1fr;
        gap: var(--s-2) var(--s-4);
        align-items: center;
        margin-block: 0.9rem;
    }
    .llms-head {
        grid-column: 1 / -1;
        display: flex;
        gap: var(--s-3);
        align-items: baseline;
    }
    .llms-head button {
        margin-inline-start: auto;
    }
    .llms .label,
    .llms label {
        font-size: var(--t-xs);
        color: var(--dim);
    }
    .llms .label {
        font-weight: 600;
    }
    .wide-cell {
        grid-column: 2 / -1;
    }
    @media (max-width: 640px) {
        .llms {
            grid-template-columns: 1fr;
        }
        .wide-cell {
            grid-column: auto;
        }
    }
    h4 {
        margin-block: 1rem 0.4rem;
    }
</style>
