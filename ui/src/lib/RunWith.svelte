<script lang="ts">
    import Pick from "./Pick.svelte";
    import Icon from "./Icon.svelte";
    import { api } from "./api";
    import type { HarnessModel, Prefs } from "./types";

    /* Which agent, which LLM, how hard, how long — one row, beside the button
     * that runs it.
     *
     * B146: "im unable to see the options for resource and effort limit". They
     * existed: the per-agent LLM and effort were a card each on Agents, two
     * screens below the fold and nowhere near a button that starts a run.
     *
     * LLM and effort are written as the agent's own preference — the same key
     * Agents writes — rather than sent with this one run, so a choice made
     * here and one made there can never disagree. Only the agent and the time
     * limit are per-run, bound to the caller.
     */
    let {
        harness = $bindable(""),
        disabled = false,
        /** Seconds, or 0 for the server's own ceiling. Drawn only when the
         *  caller passes `timeouts` — i.e. its endpoint takes one. */
        timeout = $bindable(0),
        timeouts = [],
    }: {
        harness?: string;
        disabled?: boolean;
        timeout?: number;
        timeouts?: { seconds: number; label: string }[];
    } = $props();

    let prefs = $state<Prefs | null>(null);
    let note = $state("");
    api.prefs()
        .then((data) => (prefs = data))
        .catch(() => (prefs = null));

    const harnesses = $derived<HarnessModel[]>(prefs?.harnesses ?? []);
    const preferred = $derived(prefs?.chosen?.preferred_harness ?? "");
    const active = $derived(
        harnesses.find((one) => one.id === (harness || preferred)) ?? harnesses[0],
    );
    const labelOf = (id: string) => harnesses.find((one) => one.id === id)?.label ?? id;
    const key = (prefix: string, id: string) => `${prefix}_${id.replace(/-/g, "_")}`;

    async function save(values: Record<string, string>) {
        try {
            prefs = await api.savePrefs(values);
            note = `Saved for ${active?.label ?? "this agent"}`;
        } catch (thrown) {
            note = `Could not save: ${thrown instanceof Error ? thrown.message : String(thrown)}`;
        }
    }
</script>

{#if harnesses.length}
    <div class="runwith" role="group" aria-label="Run with">
        <label class="dial">
            <span><Icon name="agent" size={14} /> Agent</span>
            <select bind:value={harness} {disabled}>
                <option value="">
                    {preferred ? `Preferred — ${labelOf(preferred)}` : `Automatic — ${harnesses[0].label}`}
                </option>
                {#each harnesses as one (one.id)}
                    <option value={one.id}>{one.label}</option>
                {/each}
            </select>
        </label>
        {#if active?.llm_selectable}
            <div class="dial">
                <span><Icon name="llm" size={14} /> LLM</span>
                <Pick
                    value={active.llm ?? ""}
                    options={(active.llms ?? []).map((name) => ({ value: name }))}
                    emptyLabel="CLI default"
                    {disabled}
                    onpick={(chosen) => save({ [key("harness_model", active.id)]: chosen })}
                />
            </div>
        {/if}
        {#if (active?.efforts ?? []).length}
            <label class="dial">
                <span><Icon name="effort" size={14} /> Effort</span>
                <select
                    value={active.effort ?? ""}
                    {disabled}
                    onchange={(event) =>
                        save({ [key("harness_effort", active.id)]: event.currentTarget.value })}
                >
                    <option value="">CLI default</option>
                    {#each active.efforts ?? [] as level (level)}
                        <option value={level}>{level}</option>
                    {/each}
                </select>
            </label>
        {/if}
        {#if timeouts.length}
            <label class="dial">
                <span><Icon name="schedule" size={14} /> Stop after</span>
                <select bind:value={timeout} {disabled}>
                    {#each timeouts as one (one.seconds)}
                        <option value={one.seconds}>{one.label}</option>
                    {/each}
                </select>
            </label>
        {/if}
    </div>
    <p class="meta hint" aria-live="polite">
        {note || "Lower effort answers sooner and costs less. LLM and effort are remembered per agent."}
    </p>
{/if}

<style>
    .runwith {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2) var(--s-3);
        align-items: flex-end;
        margin-block-start: var(--s-2);
    }
    .dial {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        flex: 1 1 9rem;
        max-width: 14rem;
    }
    .dial > span {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.8rem;
        color: var(--ink-2);
    }
    .hint {
        margin-block: var(--s-1) var(--s-2);
    }
</style>
