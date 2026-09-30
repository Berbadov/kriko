<script lang="ts">
    import Icon from "./Icon.svelte";
    import Menu from "./Menu.svelte";
    import { api } from "./api";
    import type { HarnessModel, Prefs } from "./types";

    /* Which agent, which LLM, how hard, how long: one row, beside the button
     * that runs it.
     *
     * B146: "im unable to see the options for resource and effort limit". They
     * existed on Agents, two screens below the fold and nowhere near a button
     * that starts a run.
     *
     * B175: the row is compact (a caption and a choice each, no paragraph), the
     * choices carry the provider's mark, and the LLM list is asked of the CLI
     * when the screen opens (`/api/prefs?fresh=true`) rather than read from a
     * ten-minute cache, because models change daily. Until that answer lands
     * the cached list is shown with a spinner, so the row is never empty
     * while it waits.
     *
     * LLM and effort are written as the agent's own preference, the same key
     * Agents writes, rather than sent with this one run, so a choice made
     * here and one made there can never disagree. Only the agent and the time
     * limit are per-run, bound to the caller.
     */
    let {
        harness = $bindable(""),
        disabled = false,
        /** Seconds, or 0 for the server's own ceiling. Drawn only when the
         *  caller passes `timeouts`, i.e. its endpoint takes one. */
        timeout = $bindable(0),
        timeouts = [],
    }: {
        harness?: string;
        disabled?: boolean;
        timeout?: number;
        timeouts?: { seconds: number; label: string }[];
    } = $props();

    let prefs = $state<Prefs | null>(null);
    let refreshing = $state(true);
    let failed = $state("");
    api.prefs()
        .then((data) => (prefs = data))
        .catch(() => (prefs = null));
    // Asked of the CLI itself. The cached answer above paints first; this one
    // replaces it, and a failure keeps what was already on screen.
    api.prefs(true)
        .then((data) => (prefs = data))
        .catch(() => {})
        .finally(() => (refreshing = false));

    const harnesses = $derived<HarnessModel[]>(prefs?.harnesses ?? []);
    const preferred = $derived(prefs?.chosen?.preferred_harness ?? "");
    const active = $derived(
        harnesses.find((one) => one.id === (harness || preferred)) ?? harnesses[0],
    );
    const key = (prefix: string, id: string) => `${prefix}_${id.replace(/-/g, "_")}`;

    async function save(values: Record<string, string>) {
        failed = "";
        try {
            prefs = await api.savePrefs(values);
        } catch (thrown) {
            failed = `Could not save: ${thrown instanceof Error ? thrown.message : String(thrown)}`;
        }
    }

    const agentOptions = $derived(
        harnesses.map((one) => ({ value: one.id, label: one.label, mark: one.id })),
    );
    const llmOptions = $derived([
        { value: "", label: "CLI default", mark: active?.id },
        ...(active?.llms ?? []).map((name) => ({ value: name, mark: name })),
    ]);
    const effortOptions = $derived([
        { value: "", label: "CLI default" },
        ...(active?.efforts ?? []).map((level) => ({ value: level })),
    ]);
    const timeoutOptions = $derived(
        timeouts.map((one) => ({ value: String(one.seconds), label: one.label })),
    );
</script>

{#if harnesses.length}
    <div class="runwith" role="group" aria-label="Run with">
        <div class="dial">
            <span class="cap"><Icon name="agent" size={14} /> Agent</span>
            <Menu
                label="Agent"
                {disabled}
                value={active?.id ?? ""}
                options={agentOptions}
                onpick={(picked) => (harness = picked)}
            />
        </div>
        {#if active?.llm_selectable && (active.llms ?? []).length}
            <div class="dial">
                <span class="cap"><Icon name="llm" size={14} /> LLM</span>
                <Menu
                    label="LLM"
                    {disabled}
                    busy={refreshing}
                    value={active.llm ?? ""}
                    options={llmOptions}
                    onpick={(chosen) => save({ [key("harness_model", active.id)]: chosen })}
                />
            </div>
        {/if}
        {#if (active?.efforts ?? []).length}
            <div class="dial">
                <span class="cap"><Icon name="effort" size={14} /> Effort</span>
                <Menu
                    label="Effort"
                    {disabled}
                    value={active.effort ?? ""}
                    options={effortOptions}
                    onpick={(chosen) => save({ [key("harness_effort", active.id)]: chosen })}
                />
            </div>
        {/if}
        {#if timeouts.length}
            <div class="dial">
                <span class="cap"><Icon name="schedule" size={14} /> Stop after</span>
                <Menu
                    label="Stop after"
                    {disabled}
                    value={String(timeout)}
                    options={timeoutOptions}
                    onpick={(chosen) => (timeout = Number(chosen))}
                />
            </div>
        {/if}
    </div>
    {#if failed}
        <p class="state error" role="alert">{failed}</p>
    {/if}
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
        min-width: 0;
    }
    .cap {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.8rem;
        color: var(--ink-2);
    }
</style>
