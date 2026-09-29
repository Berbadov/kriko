<script lang="ts">
    import { onMount, tick } from "svelte";
    import { api } from "../api";

    /* The close button's notice (B152). The shell used to answer X with a
     * native message box — the OS's chrome, the OS's warning sound, every
     * time. Now the shell calls `window.__krikoClose()` and waits a moment
     * for this to answer through the engine: "ack" (the notice is up), then
     * "hide" or "quit". A reader who ticked "Don't show this again" is hidden
     * at once, silently. */
    let open = $state(false);
    let remember = $state(false);
    let busy = $state(false);
    let keep = $state<HTMLButtonElement>();
    let box = $state<HTMLDivElement>();

    async function closeRequested() {
        if (open) return;
        let notice = true;
        try {
            notice = (await api.window()).close_notice;
        } catch {
            // No engine to ask: the shell hides the window on its own.
            return;
        }
        if (!notice) {
            await api.windowAction("hide").catch(() => {});
            return;
        }
        await api.windowAction("ack").catch(() => {});
        remember = false;
        open = true;
        await tick();
        keep?.focus();
    }

    async function answer(action: "hide" | "quit") {
        busy = true;
        try {
            await api.windowAction(action, action === "hide" && remember);
        } finally {
            busy = false;
            open = false;
        }
    }

    function onKeydown(event: KeyboardEvent) {
        if (!open) return;
        if (event.key === "Escape") {
            event.preventDefault();
            open = false;
        } else if (event.key === "Tab" && box) {
            // aria-modal is a promise: Tab stays inside the box.
            const stops = [...box.querySelectorAll<HTMLElement>("input, button:not([disabled])")];
            if (!stops.length) return;
            const at = stops.indexOf(document.activeElement as HTMLElement);
            const next = event.shiftKey ? (at <= 0 ? stops.length - 1 : at - 1)
                                        : (at === stops.length - 1 ? 0 : at + 1);
            event.preventDefault();
            stops[next].focus();
        }
    }

    onMount(() => {
        const host = window as unknown as { __krikoClose?: () => void };
        host.__krikoClose = () => void closeRequested();
        return () => {
            if (host.__krikoClose) delete host.__krikoClose;
        };
    });
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
    <div class="close-scrim" role="presentation" onclick={() => (open = false)}></div>
    <div
        class="close-notice enter"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="close-notice-title"
        aria-describedby="close-notice-body"
        tabindex="-1"
        bind:this={box}
    >
        <div class="close-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22">
                <path d="M4 17h16M7 17V9l5-4 5 4v8" fill="none" stroke="currentColor"
                      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                <circle cx="12" cy="12.5" r="1.6" fill="currentColor" />
            </svg>
        </div>
        <h2 id="close-notice-title">Kriko keeps running</h2>
        <p id="close-notice-body">
            The window closes, and Kriko stays in the tray by the clock so the
            browser extension can still reach it. Click the tray icon to come
            back.
        </p>
        <label class="close-remember">
            <input type="checkbox" bind:checked={remember} />
            Don't show this again
        </label>
        <div class="close-actions">
            <button type="button" class="ghost" disabled={busy} onclick={() => answer("quit")}>
                Quit Kriko
            </button>
            <button type="button" class="primary" disabled={busy} bind:this={keep}
                    onclick={() => answer("hide")}>
                Keep running
            </button>
        </div>
    </div>
{/if}

<style>
    .close-scrim {
        position: fixed;
        inset: 0;
        z-index: 60;
        background: var(--scrim);
        backdrop-filter: blur(3px);
    }
    .close-notice {
        position: fixed;
        z-index: 61;
        inset-block-start: 50%;
        inset-inline-start: 50%;
        translate: -50% -50%;
        width: min(26rem, calc(100vw - var(--s-5)));
        padding: var(--s-5);
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        box-shadow: var(--shadow-2);
    }
    .close-mark {
        display: grid;
        place-items: center;
        width: 40px;
        height: 40px;
        margin-block-end: var(--s-3);
        border-radius: 50%;
        color: var(--accent);
        background: color-mix(in srgb, var(--accent) 14%, transparent);
    }
    h2 {
        margin: 0 0 var(--s-2);
        font-size: var(--t-md);
        line-height: var(--lh-md);
    }
    p {
        margin: 0 0 var(--s-4);
        color: var(--dim);
        font-size: var(--t-sm);
        line-height: var(--lh-sm);
    }
    .close-remember {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        font-size: var(--t-sm);
        color: var(--dim);
        cursor: pointer;
    }
    .close-actions {
        display: flex;
        justify-content: flex-end;
        gap: var(--s-2);
        margin-block-start: var(--s-5);
    }
</style>
