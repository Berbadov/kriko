<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import { count } from "../lib/plural";
    import Async from "../lib/Async.svelte";
    import Keys from "../lib/Keys.svelte";
    import PlanePrefs from "../lib/Planes.prefs.svelte";
    import LocalMachine from "../lib/LocalMachine.svelte";
    import { api } from "../lib/api";
    import type { ProviderTest } from "../lib/types";

    /* Where a preference lives, and the fact that it lives anywhere.
     *
     * `/api/settings` has existed since the first week and had no screen, and
     * nothing anywhere told the reader what was being remembered on their disk.
     * For a local-first app that is the wrong silence — "what does it keep
     * about me" is answerable here in full, because the answer is short and the
     * honest way to say it is to print it.
     *
     * There is no theme choice (B159: Panel is the only theme) and no mode
     * choice (B165: there is one mode). An older install may still hold a
     * `theme` or a `mode` row, which is listed below like any other stored
     * value and is never read.
     */

    // null until the reader flips it; the {#await} below holds the stored value.
    let closeNotice = $state<boolean | null>(null);
    async function toggleCloseNotice(on: boolean) {
        closeNotice = (await api.setCloseNotice(on)).close_notice;
    }

    // Read once for the raw list.
    let stored = $state<Record<string, unknown> | null>(null);
    const promise = api.settings();
    $effect(() => {
        void promise.then((values) => (stored = values)).catch(() => {});
    });

    type Check = ProviderTest & { busy: boolean };

    let keysPromise = $state(api.keys());
    let checks = $state<Record<string, Check>>({});
    // Bumped whenever a key is saved or forgotten (settings-4): the "Check a
    // provider key" list, the search-provider select and the LLM panel below
    // each hold their own copy of the same facts and none of them re-fetch
    // on their own when a sibling component changes the underlying key.
    let keysVersion = $state(0);

    function onKeysChanged() {
        keysPromise = api.keys();
        checks = {};
        keysVersion += 1;
    }

    const blank = (providerId: string, busy: boolean): Check => ({
        provider: providerId,
        ok: false,
        latency_ms: 0,
        error: "",
        detail: "",
        results: null,
        tokens_in: null,
        tokens_out: null,
        tokens: null,
        usd: null,
        llm: "",
        busy,
    });

    async function testProvider(providerId: string) {
        checks[providerId] = blank(providerId, true);
        try {
            const verdict = await api.testKey(providerId);
            checks[providerId] = { ...verdict, busy: false };
        } catch (thrown) {
            const detail = thrown instanceof Error ? thrown.message : String(thrown);
            checks[providerId] = { ...blank(providerId, false), error: "request", detail };
        }
    }

    const checkOf = (providerId: string): Check | undefined => checks[providerId];
</script>

<h2><Icon name="settings" size={22} /> Settings</h2>
<p class="lede">
    Preferences are remembered in this install's own database, never in a
    catalog, so uninstalling knowledge cannot change how the app behaves.
    Research keys are the exception and are kept in a file of their own, below.
</p>

<!-- Before "what is remembered", because it is the one thing on this page
     that is *not* in app.sqlite, and the section below says so. -->
<Keys onChange={onKeysChanged} />

{#await api.window() then win}
    {#if win.shell}
        <section>
            <h3><Icon name="monitor" /> Closing the window</h3>
            <label class="choice" class:on={closeNotice ?? win.close_notice}>
                <input
                    type="checkbox"
                    checked={closeNotice ?? win.close_notice}
                    onchange={(e) => toggleCloseNotice(e.currentTarget.checked)}
                />
                <span>Say that Kriko keeps running in the tray when I close the window</span>
            </label>
        </section>
    {/if}
{:catch}
    <!-- No engine answer: nothing to switch, and the rest of Settings stands. -->
{/await}

<section>
    <h3><Icon name="key" /> Check a provider key</h3>
    <p class="meta">
        Each press sends one small search or one short reply request from the
        server, then reports what the provider answered. Nothing on this screen
        ever shows a key.
    </p>
    <Async promise={keysPromise} loading="Reading...">
        {#snippet children(data)}
            <ul class="checks">
                {#each (data.providers ?? []) as provider (provider.id)}
                    {@const check = checkOf(provider.id)}
                    <li class="check">
                        <div class="check-head">
                            <strong>{provider.label}</strong>
                            {#if provider.present}
                                <span class="badge fact-ok">set {provider.hint}</span>
                            {:else}
                                <span class="badge">not set</span>
                            {/if}
                            <button
                                type="button"
                                disabled={!provider.present || check?.busy}
                                onclick={() => testProvider(provider.id)}
                            >
                                {check?.busy ? "Testing..." : "Test"}
                            </button>
                        </div>
                        {#if check}
                            {#if check.busy}
                                <p class="state" role="status">Testing...</p>
                            {:else if check.ok}
                                <p class="state fact-ok" role="status">
                                    ok in {check.latency_ms} ms{#if check.results !== null}
                                        · {count(check.results, "result")}{/if}{#if check.tokens !== null}
                                        · {check.tokens} tokens{/if}
                                </p>
                            {:else if check.error}
                                <p class="state" role="status">
                                    {check.error}{#if check.detail}: {check.detail}{/if}
                                </p>
                            {/if}
                        {/if}
                    </li>
                {/each}
            </ul>
        {/snippet}
    </Async>
</section>

<!-- Which agent, which LLM, which search provider — and what the runs have
     actually cost. Under the keys because a choice between providers only
     means something once a key exists for one of them. -->
<PlanePrefs {keysVersion} />

<LocalMachine />

<section>
    <h3><Icon name="database" /> What is remembered</h3>
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
    /* `.choice` is global now (components.css): a raised card, like a button. */
    /* Four short rows side by side where they fit (B146). */
    .checks {
        list-style: none;
        padding: 0;
        margin-block: var(--s-3);
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
        gap: var(--s-2);
    }
    .check {
        padding: var(--s-2);
        border: 1px solid var(--line);
        border-radius: var(--radius);
    }
    .check-head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
</style>
