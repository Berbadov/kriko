<script lang="ts">
    /* Choose an LLM or an agent by *choosing* it.
     *
     * The reader's sentence: "I want to click and select models/harnesses,
     * not type their name." Every one of these was an `<input list=…>` — a
     * text field with a datalist attached — which is the control that looks
     * like a dropdown and is not one. It offers nothing until you find a
     * small chevron or start typing, it accepts anything including a typo
     * that only fails minutes later inside a spawned CLI, and on some
     * browsers it shows no list at all. There were five, across four screens.
     *
     * So: a real `<select>`, holding the names the CLI itself reported, and
     * one last entry that opens a text field for a name Kriko has never
     * heard of. That entry is not politeness. The CLI judges the name, not
     * Kriko — a reader on a build newer than this one must be able to name an
     * LLM that did not exist when this shipped, and a control that forbade it
     * would be a worse bug than the one it replaced.
     *
     * `""` is always the first option, because leaving one of these alone is
     * what almost every installation does.
     */
    let {
        value = $bindable(""),
        options = [],
        /** What `""` means here, in the reader's words — "CLI default",
         *  "Use preference". Never a blank line in the list. */
        emptyLabel = "Default",
        /** Why this name may be free-form, shown under the custom field. */
        hint = "",
        /** Why `options` is empty, said in one line ("This CLI does not list
         *  its models"). With no options and a note the list is replaced by the
         *  line and a field for typing a name, since the CLI judges the name. */
        note = "",
        id = "",
        disabled = false,
        onpick,
    }: {
        value?: string;
        options?: { value: string; label?: string; note?: string; disabled?: boolean }[];
        emptyLabel?: string;
        hint?: string;
        note?: string;
        id?: string;
        disabled?: boolean;
        onpick?: (value: string) => void;
    } = $props();

    const CUSTOM = "\u0000custom";

    /* Sticky once opened, so a reader halfway through typing a name does not
     * lose the field the moment the value momentarily matches nothing. */
    let typing = $state(false);
    const known = $derived(options.some((one) => one.value === value));
    /* A value that arrived from the server and is not in the list is a real
     * custom choice, and has to show as one — otherwise the dropdown reads
     * "Default" while the run uses something else, which is the class of bug
     * this whole change is about. */
    const custom = $derived(typing || (!!value && !known));
    const unlisted = $derived(!options.length && !!note);

    function choose(next: string) {
        if (next === CUSTOM) {
            typing = true;
            return;
        }
        typing = false;
        value = next;
        onpick?.(next);
    }

    function type(next: string) {
        value = next;
        onpick?.(next);
    }
</script>

{#if unlisted}
    <p class="meta">{note}</p>
    <input
        {id}
        {disabled}
        value={value ?? ""}
        placeholder={emptyLabel}
        aria-label="Custom name"
        onchange={(event) => type(event.currentTarget.value)}
    />
    {#if hint}<p class="meta">{hint}</p>{/if}
{:else}
<select
    {id}
    {disabled}
    value={custom ? CUSTOM : value}
    onchange={(event) => choose(event.currentTarget.value)}
>
    <option value="">{emptyLabel}</option>
    {#each options as one (one.value)}
        <option value={one.value} disabled={one.disabled} title={one.note ?? ""}>
            {one.label ?? one.value}{one.note ? ` — ${one.note}` : ""}
        </option>
    {/each}
    <option value={CUSTOM}>Something else…</option>
</select>

{#if custom}
    <input
        {disabled}
        value={value ?? ""}
        placeholder="type the name"
        aria-label="Custom name"
        onchange={(event) => type(event.currentTarget.value)}
    />
    {#if hint}<p class="meta">{hint}</p>{/if}
{/if}
{/if}

<style>
    input {
        margin-block-start: var(--s-2);
    }
</style>
