<script lang="ts">
    import { navigate } from "../router";
    import type { Mode } from "../mode";
    import { destinationsFor } from "./nav";

    /* Getting somewhere without reading the rail.
     *
     * The rail is the map and it stays the map. This is the shortcut for
     * someone who already knows where they are going and does not want to
     * look for it — and, just as much, it is the only place in the app that
     * says out loud that keyboard shortcuts exist. There was no `?`, so the
     * Console (a screen an author reaches constantly) was findable only by
     * scrolling a group of five, and nothing anywhere named a single key.
     *
     * Two keys open it because they mean different things to different
     * readers: ⌘K/Ctrl+K is what anyone who has used a modern editor tries
     * first, and `?` is what anyone who has used a keyboard-driven web app
     * tries first. They open the same thing rather than two half-features.
     *
     * The destinations are `destinationsFor(mode)`, not a list of its own —
     * see nav.ts. A palette that has to be told about a new screen is a
     * palette that is silently one release behind.
     */

    let { mode }: { mode: Mode } = $props();

    let open = $state(false);
    let q = $state("");
    let at = $state(0);
    let input = $state<HTMLInputElement | undefined>();
    // Where the reader was, so closing puts them back. A palette that
    // dismisses to nowhere leaves a keyboard user at the top of the document.
    let cameFrom: HTMLElement | null = null;

    const all = $derived(destinationsFor(mode));
    const hits = $derived(
        q.trim()
            ? all.filter((d) =>
                  `${d.label} ${d.group} ${d.name}`
                      .toLowerCase()
                      .includes(q.trim().toLowerCase()),
              )
            : all,
    );

    // Clamped rather than reset: typing narrows the list under the cursor, and
    // an index left past the end leaves Enter with nothing to open.
    const cursor = $derived(Math.min(at, Math.max(0, hits.length - 1)));

    /** A keystroke meant for a text field is not a shortcut.
     *
     * Without this, `?` in the Console's request body — or in any note, or
     * any search box — would open the palette over what the reader was
     * typing. `contentEditable` is included because a rich field is the same
     * problem wearing a different tag. */
    function typing(target: EventTarget | null): boolean {
        const el = target as HTMLElement | null;
        if (!el) return false;
        if (el.isContentEditable) return true;
        return ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
    }

    function show() {
        cameFrom = document.activeElement as HTMLElement | null;
        q = "";
        at = 0;
        open = true;
    }

    function hide() {
        open = false;
        cameFrom?.focus?.();
        cameFrom = null;
    }

    function go(name: string) {
        open = false;
        cameFrom = null;
        navigate(name);
    }

    function onKeydown(event: KeyboardEvent) {
        if (!open) {
            const combo = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
            const help = event.key === "?" && !typing(event.target);
            if (combo || help) {
                event.preventDefault();
                show();
            }
            return;
        }
        if (event.key === "Escape") {
            event.preventDefault();
            hide();
            return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!hits.length) return;
            const step = event.key === "ArrowDown" ? 1 : -1;
            at = (cursor + step + hits.length) % hits.length;
            return;
        }
        if (event.key === "Enter") {
            event.preventDefault();
            const chosen = hits[cursor];
            if (chosen) go(chosen.name);
        }
    }

    $effect(() => {
        if (open) input?.focus();
    });
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
    <!-- The scrim closes on click, which is what every reader tries first.
         It carries no keyboard handler of its own: Escape is on the window
         above, so the behaviour does not depend on where focus happens to be
         inside the dialog.

         It is a *sibling* of the dialog rather than its parent. As a parent it
         would need `stopPropagation` on the dialog to keep a click inside the
         palette from closing it — a click handler on a non-interactive
         wrapper whose entire job is to cancel another one. Two siblings and a
         z-index say the same thing without the handler. -->
    <div class="scrim" role="presentation" onclick={hide}></div>
    <div
        class="palette enter"
        role="dialog"
        aria-modal="true"
        aria-label="Go to a screen"
        tabindex="-1"
    >
        <input
            bind:this={input}
            bind:value={q}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={hits.length ? `palette-${hits[cursor].name}` : undefined}
            aria-label="Search screens"
            placeholder="Go to…"
            spellcheck="false"
            autocomplete="off"
            oninput={() => (at = 0)}
        />
        {#if hits.length}
            <ul id="palette-list" role="listbox" aria-label="Screens">
                {#each hits as hit, i (hit.name)}
                    <li
                        id="palette-{hit.name}"
                        role="option"
                        aria-selected={i === cursor}
                        class:on={i === cursor}
                    >
                        <button type="button" onclick={() => go(hit.name)}>
                            <span class="label">{hit.label}</span>
                            <span class="meta">{hit.group}</span>
                        </button>
                    </li>
                {/each}
            </ul>
        {:else}
            <p class="state empty">
                No screen called that. {mode === "buyer"
                    ? "Some of them only exist in author mode."
                    : "Try a word from the rail."}
            </p>
        {/if}
        <p class="keys">
            <kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Enter</kbd> open ·
            <kbd>Esc</kbd> close · <kbd>?</kbd> or <kbd>Ctrl</kbd>+<kbd>K</kbd>
            opens this from anywhere
        </p>
    </div>
{/if}

<style>
    .scrim {
        position: fixed;
        inset: 0;
        z-index: 50;
        background: var(--scrim);
    }
    .palette {
        position: fixed;
        z-index: 51;
        inset-block-start: 12vh;
        inset-inline-start: 50%;
        translate: -50% 0;
        width: min(30rem, calc(100vw - var(--s-5)));
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        box-shadow: var(--shadow-2);
        overflow: hidden;
    }
    .palette input {
        width: 100%;
        box-sizing: border-box;
        border: 0;
        border-block-end: 1px solid var(--line);
        border-radius: 0;
        font-size: var(--t-md);
        line-height: var(--lh-md);
        padding: var(--s-3);
    }
    .palette ul {
        list-style: none;
        margin: 0;
        padding: var(--s-1);
        max-height: 45vh;
        overflow-y: auto;
    }
    .palette li button {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: var(--s-3);
        width: 100%;
        text-align: start;
        background: transparent;
        border: 0;
        border-radius: var(--radius-sm);
        padding: var(--s-2) var(--s-3);
        cursor: pointer;
        color: inherit;
    }
    .palette li.on button,
    .palette li button:hover {
        background: var(--accent-soft);
    }
    .palette .state.empty {
        margin: var(--s-3);
    }
    .keys {
        margin: 0;
        padding: var(--s-2) var(--s-3);
        border-block-start: 1px solid var(--line);
        color: var(--dim);
        font-size: var(--t-xs);
        line-height: var(--lh-xs);
    }
</style>
