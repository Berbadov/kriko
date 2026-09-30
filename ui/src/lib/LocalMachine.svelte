<script lang="ts">
    import Icon from "./Icon.svelte";
    import { api } from "./api";
    import type { LocalPlane } from "./types";

    /* The local machine plane's settings (B171): where the model server is,
     * which of its models to use, where search is, how long to wait. Every
     * list and every sentence comes from `/api/local-plane`; nothing here names
     * a server or a model. Compact on purpose, B184 polishes it. */
    let status = $state<LocalPlane | null>(null);
    let failed = $state("");
    let saved = $state("");
    let url = $state("");
    let model = $state("");
    let searchUrl = $state("");
    let timeout = $state("");
    let busy = $state(false);

    async function load(fillForm: boolean) {
        busy = true;
        failed = "";
        try {
            status = await api.localPlane();
            if (fillForm) {
                url = status.stored.local_url;
                model = status.stored.local_model;
                searchUrl = status.stored.local_search_url;
                timeout = status.stored.local_timeout;
            }
        } catch (thrown) {
            failed = thrown instanceof Error ? thrown.message : String(thrown);
        } finally {
            busy = false;
        }
    }

    async function save() {
        saved = "";
        await api.savePrefs({
            local_url: url,
            local_model: model,
            local_search_url: searchUrl,
            local_timeout: timeout,
        });
        saved = "Saved.";
        await load(false);
    }

    $effect(() => {
        void load(true);
    });
</script>

<section>
    <h3><Icon name="monitor" /> Local machine</h3>
    <p class="meta">
        A model running on this computer reads for Kriko, at no cost and with no key.
    </p>
    {#if failed}
        <p class="state" role="status">Could not read the local plane: {failed}</p>
    {:else if !status}
        <p class="state loading">Checking…</p>
    {:else}
        <p class="state" class:fact-ok={status.ready} role="status">{status.line}</p>
        <div class="fields">
            <label>
                Server address
                <input
                    type="url"
                    bind:value={url}
                    placeholder="Found automatically"
                    autocomplete="off"
                />
            </label>
            <label>
                Model
                <select bind:value={model}>
                    <option value="">First one the server lists</option>
                    {#each status.models as one (one)}
                        <option value={one}>{one}</option>
                    {/each}
                </select>
            </label>
            <label>
                Search service address
                <input
                    type="url"
                    bind:value={searchUrl}
                    placeholder="http://127.0.0.1:7000"
                    autocomplete="off"
                />
            </label>
            <label>
                Wait for one answer, in seconds
                <input type="number" min="10" bind:value={timeout} placeholder="300" />
            </label>
        </div>
        <div class="row">
            <button type="button" onclick={save} disabled={busy}>Save</button>
            <button type="button" onclick={() => load(false)} disabled={busy}>Check again</button>
            {#if saved}<span class="meta" role="status">{saved}</span>{/if}
        </div>
    {/if}
</section>

<style>
    section {
        margin-block: var(--s-5);
    }
    .fields {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
        gap: var(--s-2);
        margin-block: var(--s-3);
    }
    .fields label {
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
    }
    .row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
</style>
