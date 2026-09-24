<script lang="ts">
    /* An agent's LLM, picked from what that agent's own CLI names.
     *
     * Three screens chose this with a text box and a `<datalist>`, which reads
     * as "type a name" — the names were there, behind a caret Chromium
     * only shows on hover. A select says what the CLI offers; "Other…" keeps
     * the door open for a name it did not list, because the CLI judges the
     * name, not Kriko.
     *
     * `value` is the choice; `""` means "the default", whose meaning the
     * caller names in `defaultLabel` (the stored preference, or the CLI's own).
     */
    let {
        llms = [],
        value = $bindable(""),
        defaultLabel = "CLI default",
        hint = "",
        disabled = false,
        id = "",
        label = "",
        labelOf = (name: string) => name,
        onchange,
    }: {
        llms?: string[];
        value?: string;
        defaultLabel?: string;
        hint?: string;
        disabled?: boolean;
        id?: string;
        label?: string;
        /** What an option reads as, when its name is not the whole story. */
        labelOf?: (name: string) => string;
        onchange?: (value: string) => void;
    } = $props();

    const OTHER = "__other__";
    let typing = $state(false);
    const custom = $derived(typing || (value !== "" && !llms.includes(value)));

    function pick(next: string) {
        if (next === OTHER) {
            typing = true;
            return;
        }
        typing = false;
        value = next;
        onchange?.(next);
    }
</script>

<span class="pick">
    <select
        {id}
        aria-label={label || undefined}
        {disabled}
        value={custom ? OTHER : value}
        onchange={(event) => pick(event.currentTarget.value)}
    >
        <option value="">{defaultLabel}</option>
        {#each llms as name (name)}
            <option value={name}>{labelOf(name)}</option>
        {/each}
        <option value={OTHER}>Other…</option>
    </select>
    {#if custom}
        <input
            aria-label={label ? `${label}, typed` : "LLM name"}
            {disabled}
            {value}
            placeholder={hint || "a name the CLI accepts"}
            onchange={(event) => {
                value = event.currentTarget.value.trim();
                if (!value) typing = false;
                onchange?.(value);
            }}
        />
    {/if}
</span>

<style>
    .pick {
        display: inline-flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        align-items: center;
    }
</style>
