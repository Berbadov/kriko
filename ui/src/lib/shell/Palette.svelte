<script lang="ts">
    import { hashWith } from "../router";
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
    let dialog = $state<HTMLElement | undefined>();
    // Where the reader was, so closing puts them back. A palette that
    // dismisses to nowhere leaves a keyboard user at the top of the document.
    let cameFrom: HTMLElement | null = null;

    const all = $derived(destinationsFor(mode));
    // A label match ranks ahead of a match buried in `also` or `group`, so
    // typing "browse" and pressing Enter lands on the screen actually called
    // Browse rather than on "Browser extension", which merely starts with
    // the same letters further down the (unsorted) list.
    const rank = (d: { label: string }, needle: string): number => {
        const label = d.label.toLowerCase();
        if (label === needle) return 0;
        if (label.startsWith(needle)) return 1;
        return 2;
    };

    const hits = $derived(
        q.trim()
            ? all
                  .filter((d) =>
                      // `d.also` is the vocabulary a merged screen absorbed —
                      // "console", "jobs", "submissions". Searching without it
                      // would mean the reorganisation made the app harder to
                      // search than before it, which is the wrong direction.
                      `${d.label} ${d.group} ${d.name} ${(d.also ?? []).join(" ")}`
                          .toLowerCase()
                          .includes(q.trim().toLowerCase()),
                  )
                  .slice()
                  .sort((a, b) => rank(a, q.trim().toLowerCase()) - rank(b, q.trim().toLowerCase()))
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

    // Arrow keys move the cursor, but the list itself is only 45vh tall (it
    // is capped so the palette never grows past the window) — at a short
    // window that is well under the full option count, so without this the
    // highlighted option scrolls out of view and Enter opens a destination
    // the reader cannot see was selected.
    function scrollActiveIntoView() {
        if (!hits.length) return;
        // Optional call, not just optional lookup: jsdom's HTMLElement has no
        // scrollIntoView at all, and the tests run there — a bare `?.` on
        // the element would still throw calling an undefined method.
        document
            .getElementById(`palette-${hits[cursor].name}`)
            ?.scrollIntoView?.({ block: "nearest" });
    }

    // The rail's own links carry only the mode, never the screen's own
    // filters (a lens, an id, a search term) — a jump from #/questions?id=X
    // has no business landing on the next screen with ?id=X still attached.
    // `navigate()` copies the whole current query, which is right for a link
    // that means "same place, new mode"; the palette means "somewhere else
    // entirely", so it builds the hash itself, the way the rail does.
    function go(name: string) {
        open = false;
        cameFrom = null;
        window.location.hash = hashWith({ mode }, name);
    }

    /** Tab, wrapped at the two ends.
     *
     * `aria-modal="true"` is a claim, and it was one this dialog did not keep:
     * tab off the last option and focus walked into the rail behind the scrim
     * — a link the reader cannot see, with no visible ring anywhere on screen
     * and no reason left to think Escape is listening.
     *
     * The stops are read off the dialog at the moment of the press rather than
     * held in a variable, because the list is filtered as the reader types:
     * anything captured on open is wrong by the second keystroke. Only the two
     * ends are intercepted — a handler that preventDefaults every Tab leaves
     * the middle of the list unwalkable, which is the same bug facing the
     * other way.
     */
    function trap(event: KeyboardEvent): void {
        if (!dialog) return;
        const stops = [
            ...dialog.querySelectorAll<HTMLElement>(
                "input, button:not([disabled]), a[href]",
            ),
        ];
        if (stops.length < 2) return;
        const first = stops[0];
        const last = stops[stops.length - 1];
        const on = document.activeElement;
        if (!event.shiftKey && on === last) {
            event.preventDefault();
            first.focus();
        } else if (event.shiftKey && on === first) {
            event.preventDefault();
            last.focus();
        }
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
        if (event.key === "Tab") {
            trap(event);
            return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!hits.length) return;
            const step = event.key === "ArrowDown" ? 1 : -1;
            at = (cursor + step + hits.length) % hits.length;
            scrollActiveIntoView();
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
        bind:this={dialog}
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
