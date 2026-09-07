<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";
    import { MODES, mode, setMode } from "../lib/mode";
    import { THEMES, THEME_LABELS, setTheme, theme } from "../lib/theme";

    /* Where a preference lives, and the fact that it lives anywhere.
     *
     * `/api/settings` has existed since the first week and had no screen: the
     * theme switcher was a heading down the About page, the mode switch was a
     * rail control that quietly wrote a row, and nothing anywhere told the
     * reader that either was being remembered on their disk. For a local-first
     * app that is the wrong silence — "what does it keep about me" is
     * answerable here in full, because the answer is short and the honest way
     * to say it is to print it.
     */

    const MODE_WORDS: Record<string, string> = {
        buyer: "What to worry about, and what to ask — the default.",
        author: "The same answer plus why it ranked there, and which pack said so.",
    };

    // Read once for the raw list. The two controls above it drive the stores
    // directly, so this is a snapshot of the table rather than the source of
    // what is on screen — refreshed after a change so the list cannot
    // disagree with the switch that just moved.
    let stored = $state<Record<string, unknown> | null>(null);
    let promise = $state(api.settings());
    $effect(() => {
        void promise.then((values) => (stored = values)).catch(() => {});
    });

    const refresh = () => {
        promise = api.settings();
    };

    function pickTheme(id: (typeof THEMES)[number]) {
        setTheme(id);
        // A beat behind the write, which is fire-and-forget by design. The
        // list is a reflection, and a reflection arriving late is fine; a
        // switch that waits for a disk write is not.
        setTimeout(refresh, 50);
    }

    function pickMode(next: (typeof MODES)[number]) {
        setMode(next);
        setTimeout(refresh, 50);
    }
</script>

<h2>Settings</h2>
<p class="lede">
    Two preferences, both remembered in this install's own database — never in a
    pack, so uninstalling knowledge cannot change how the app looks.
</p>

<section>
    <h3>Appearance</h3>
    <p class="meta">
        A theme is one complete palette, not a tweak — every colour in the app
        comes from the one you pick here.
    </p>
    <div class="choices">
        {#each THEMES as id (id)}
            <label class="choice" class:on={$theme === id}>
                <input
                    type="radio"
                    name="theme"
                    value={id}
                    checked={$theme === id}
                    onchange={() => pickTheme(id)}
                />
                <span>{THEME_LABELS[id]}</span>
            </label>
        {/each}
    </div>
</section>

<section>
    <h3>What an answer shows</h3>
    <p class="meta">
        The same lookup, read two ways. Nothing about the request changes — the
        engine answers once and this picks how much of the answer is drawn, which
        is why a link can carry a mode of its own and override this.
    </p>
    <div class="choices">
        {#each MODES as id (id)}
            <label class="choice" class:on={$mode === id}>
                <input
                    type="radio"
                    name="mode"
                    value={id}
                    checked={$mode === id}
                    onchange={() => pickMode(id)}
                />
                <span><strong>{id}</strong> — {MODE_WORDS[id]}</span>
            </label>
        {/each}
    </div>
</section>

<section>
    <h3>What is remembered</h3>
    <p class="meta">
        Everything the interface keeps about you, in full. It lives in this
        install's <code>app.sqlite</code> beside your history — not in the
        knowledge store, and not anywhere else.
    </p>
    <Async {promise} loading="Reading…">
        {#snippet children(values)}
            {#if !Object.keys(values).length}
                <p class="state empty">
                    Nothing yet — the defaults are in the code, and a row appears
                    the first time you change something.
                </p>
            {:else}
                <dl class="facts">
                    {#each Object.entries(values) as [key, value] (key)}
                        <dt>{key}</dt>
                        <dd class="path">{JSON.stringify(value)}</dd>
                    {/each}
                </dl>
            {/if}
        {/snippet}
    </Async>
</section>

<style>
    section {
        margin-block: var(--s-5);
    }
    section > .meta {
        max-width: var(--measure);
    }
    .choices {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        margin-block-start: var(--s-3);
    }
    .choice {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        padding: var(--s-2);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        cursor: pointer;
    }
    .choice.on {
        border-color: var(--accent);
    }
</style>
