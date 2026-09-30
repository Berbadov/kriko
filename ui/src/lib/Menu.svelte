<script lang="ts">
    import { tick } from "svelte";
    import Icon from "./Icon.svelte";
    import ProviderMark from "./ProviderMark.svelte";

    /* One choice out of a list, with a mark beside each entry (B175).
     *
     * A native `<select>` cannot draw anything inside an `<option>`, and the
     * reader asked to see the provider's mark on every agent and LLM. So
     * this is the `listbox` pattern: a button that shows the current choice,
     * and a list under it. The keyboard is what a select gives (Down/Up,
     * Home/End, Enter, Escape, type-ahead on the first letter) so the
     * control is not worse to use for looking better.
     *
     * `mark` on an option is the text `ProviderMark` reads (a harness id, a
     * LLM name), not a mark id, so the caller passes the data it already
     * has. Nothing here knows a provider.
     */
    type Option = { value: string; label?: string; mark?: string };
    let {
        value = $bindable(""),
        options = [],
        label,
        disabled = false,
        busy = false,
        onpick,
    }: {
        value?: string;
        options?: Option[];
        /** The control's name: the visible caption and the accessible name. */
        label: string;
        disabled?: boolean;
        /** A refresh is in flight; the arrow becomes a spinner. */
        busy?: boolean;
        onpick?: (value: string) => void;
    } = $props();

    let open = $state(false);
    let active = $state(0);
    let root: HTMLDivElement;
    let list = $state<HTMLUListElement>();

    const current = $derived(options.find((one) => one.value === value) ?? options[0]);
    const words = (one: Option | undefined) => one?.label ?? one?.value ?? "";

    async function show() {
        if (disabled || !options.length) return;
        active = Math.max(0, options.findIndex((one) => one.value === current?.value));
        open = true;
        await tick();
        list?.focus();
    }

    function hide(refocus = true) {
        open = false;
        if (refocus) root?.querySelector("button")?.focus();
    }

    function pick(index: number) {
        const one = options[index];
        if (!one) return;
        value = one.value;
        onpick?.(one.value);
        hide();
    }

    function onListKey(event: KeyboardEvent) {
        const last = options.length - 1;
        if (event.key === "ArrowDown") active = Math.min(last, active + 1);
        else if (event.key === "ArrowUp") active = Math.max(0, active - 1);
        else if (event.key === "Home") active = 0;
        else if (event.key === "End") active = last;
        else if (event.key === "Enter" || event.key === " ") pick(active);
        else if (event.key === "Escape") hide();
        else if (event.key === "Tab") hide(false);
        else if (event.key.length === 1) {
            // Type-ahead: the next entry that starts with the letter.
            const at = options.findIndex(
                (one, index) =>
                    index > active &&
                    words(one).toLowerCase().startsWith(event.key.toLowerCase()),
            );
            if (at !== -1) active = at;
            else return;
        } else return;
        event.preventDefault();
    }

    function onButtonKey(event: KeyboardEvent) {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            void show();
        }
    }

    // A click anywhere else closes it, as a select does.
    $effect(() => {
        if (!open) return;
        const away = (event: MouseEvent) => {
            if (!root.contains(event.target as Node)) hide(false);
        };
        document.addEventListener("mousedown", away);
        return () => document.removeEventListener("mousedown", away);
    });
</script>

<div class="menu" bind:this={root}>
    <button
        type="button"
        class="face"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="{label}: {words(current)}"
        {disabled}
        onclick={() => (open ? hide() : void show())}
        onkeydown={onButtonKey}
    >
        {#if current?.mark}<ProviderMark name={current.mark} />{/if}
        <span class="words">{words(current) || "None"}</span>
        {#if busy}
            <span class="spin" aria-hidden="true"></span>
        {:else}
            <span class="arrow" aria-hidden="true"><Icon name="chevron" size={14} /></span>
        {/if}
    </button>
    {#if open}
        <ul
            class="list enter"
            role="listbox"
            tabindex="-1"
            aria-label={label}
            aria-activedescendant="{label}-{active}"
            bind:this={list}
            onkeydown={onListKey}
        >
            {#each options as one, index (one.value)}
                <li
                    id="{label}-{index}"
                    role="option"
                    aria-selected={one.value === current?.value}
                    class:active={index === active}
                    onmouseenter={() => (active = index)}
                    onclick={() => pick(index)}
                    onkeydown={() => {}}
                >
                    {#if one.mark}<ProviderMark name={one.mark} />{/if}
                    <span class="words">{words(one)}</span>
                </li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .menu {
        position: relative;
        min-width: 0;
    }
    .face {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        width: 100%;
        text-align: start;
    }
    .words {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .arrow {
        display: inline-flex;
        transform: rotate(90deg);
        color: var(--dim);
    }
    .spin {
        width: 12px;
        height: 12px;
        border: 2px solid var(--line);
        border-top-color: var(--accent);
        border-radius: 50%;
        animation: menu-spin calc(var(--dur-slower) * 2) linear infinite;
    }
    @keyframes menu-spin {
        to {
            transform: rotate(360deg);
        }
    }
    @media (prefers-reduced-motion: reduce) {
        .spin {
            animation: none;
        }
    }
    .list {
        position: absolute;
        inset-inline: 0;
        z-index: 20;
        margin-block-start: var(--s-1);
        padding: var(--s-1);
        list-style: none;
        max-height: 16rem;
        overflow: auto;
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        box-shadow: var(--shadow-2);
    }
    .list:focus-visible {
        outline: none;
    }
    li {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-1) var(--s-2);
        border-radius: var(--radius-sm);
        cursor: pointer;
    }
    li.active {
        background: var(--panel-2);
    }
    li[aria-selected="true"] {
        color: var(--accent);
    }
</style>
