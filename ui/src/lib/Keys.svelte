<script lang="ts">
    import Async from "./Async.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import type { ApiKeyStatus } from "./types";

    /* The keys the paid research plane needs, and nothing else about them.
     *
     * Write-only by construction rather than by discipline. The server has no
     * surface that returns a key — `app/keys.py`'s `require` is the only
     * function that reads one and it never leaves the process — so this screen
     * cannot show a stored value even if it wanted to, and the field is empty
     * on every load rather than pre-filled with dots pretending to be a
     * secret. What comes back is a masked tail, which is enough to answer "is
     * the key I set the one I think it is" and useless to anyone else.
     *
     * Each provider prints what it *receives*, in the reader's terms, beside
     * the box asking for the key. A local-first app that starts sending data
     * to two companies owes that sentence at the point of the decision, not in
     * a privacy page — and it comes from the server, where `PROVIDERS` states
     * it once, because a copy here would be a copy to forget.
     *
     * A key already in the environment is shown and not offered a delete: the
     * app did not put it there and cannot take it out of a parent shell, and a
     * button that silently fails is worse than an explained absence.
     */

    let promise = $state(api.keys());
    /** Per provider, and cleared on save — never seeded from the server. */
    let drafts = $state<Record<string, string>>({});
    let busy = $state("");
    let said = $state("");

    const refresh = () => {
        promise = api.keys();
    };

    async function save(provider: ApiKeyStatus) {
        const value = (drafts[provider.id] ?? "").trim();
        if (!value) return;
        busy = provider.id;
        said = "";
        try {
            await api.putKeys({ [provider.id]: value });
            // Cleared immediately: a key left in a bound input is a key in the
            // DOM, in a form autofill, and in a screenshot.
            drafts[provider.id] = "";
            said = `${provider.label} saved`;
            refresh();
        } catch (cause) {
            // B79: the remedy, not the exception. A reader who cannot save a
            // key needs to know whether the engine is up, not what threw.
            said = remedyFor(cause).headline;
        } finally {
            busy = "";
        }
    }

    async function forget(provider: ApiKeyStatus) {
        busy = provider.id;
        said = "";
        try {
            await api.forgetKey(provider.id);
            said = `${provider.label} forgotten`;
            refresh();
        } catch (cause) {
            said = remedyFor(cause).headline;
        } finally {
            busy = "";
        }
    }
</script>

<section>
    <h3>Research keys</h3>
    <p class="meta">
        Only the second research plane needs these. Your coding agent researches
        for free through the MCP server and needs nothing here — these are for
        letting Kriko search and read by itself, unattended.
    </p>

    <Async {promise} loading="Reading…" retry={refresh}>
        {#snippet children(data)}
            <ul class="keys">
                {#each data.providers as provider (provider.id)}
                    <li class="key" class:on={provider.present}>
                        <div class="key-head">
                            <strong>{provider.label}</strong>
                            <code>{provider.env}</code>
                            {#if provider.present}
                                <span class="badge fact-ok">set {provider.hint}</span>
                            {:else}
                                <span class="badge">not set</span>
                            {/if}
                        </div>
                        <p class="meta">{provider.purpose}</p>

                        {#if provider.source === "environment"}
                            <!-- Set outside this app, so this app must not
                                 pretend it can remove it. -->
                            <p class="meta">
                                This one comes from the environment Kriko was started
                                in, not from the file below. Change it where you set
                                it; a value saved here would be ignored while that
                                one is present.
                            </p>
                        {:else}
                            <form
                                class="ask"
                                onsubmit={(event) => (
                                    event.preventDefault(), save(provider)
                                )}
                            >
                                <label class="field grow">
                                    <span class="meta"
                                        >{provider.present
                                            ? "Replace it"
                                            : "Paste it"}</span
                                    >
                                    <input
                                        type="password"
                                        autocomplete="off"
                                        spellcheck="false"
                                        placeholder="paste the key"
                                        bind:value={drafts[provider.id]}
                                    />
                                </label>
                                <button
                                    type="submit"
                                    disabled={busy === provider.id ||
                                        !(drafts[provider.id] ?? "").trim()}>Save</button
                                >
                                {#if provider.present}
                                    <button
                                        type="button"
                                        class="link-ish"
                                        disabled={busy === provider.id}
                                        onclick={() => forget(provider)}>Forget it</button
                                    >
                                {/if}
                            </form>
                        {/if}
                    </li>
                {/each}
            </ul>

            {#if said}
                <p class="state" role="status">{said}</p>
            {/if}

            <p class="meta">
                Stored in <code class="path">{data.path}</code>, readable only by
                you, and loaded into Kriko's environment at startup. Not in
                <code>app.sqlite</code> — a database that gets copied, backed up
                and inspected is the wrong place for a secret.
                {#if !data.ready}
                    Both are needed before the paid plane will run: it searches
                    <em>and</em> reads.
                {/if}
            </p>
        {/snippet}
    </Async>
</section>

<style>
    .keys {
        list-style: none;
        padding: 0;
        margin-block: var(--s-3);
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    .key {
        padding: var(--s-3);
        border: 1px solid var(--line);
        border-radius: var(--radius);
    }
    .key.on {
        border-color: var(--accent);
    }
    .key-head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
    .key > .meta {
        max-width: var(--measure);
    }
</style>
