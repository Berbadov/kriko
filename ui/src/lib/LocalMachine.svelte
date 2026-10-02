<script lang="ts">
    import { api } from "./api";
    import Led from "./kriko/Led.svelte";
    import Meter from "./kriko/Meter.svelte";
    import Tag from "./kriko/Tag.svelte";
    import Key from "./kriko/Key.svelte";
    import type { LocalPlane } from "./types";

    /* The local machine plane's settings (B171), on the design system's
     * own faces: where the LLM server is, which of its models to use,
     * where search is, how long to wait. Every list and every sentence
     * comes from `/api/local-plane`; nothing here names a server or an
     * LLM. The status line is a Tag - live when the plane answers, block
     * when it does not - and a check in flight shows the scan strip, the
     * same working indicator a running job carries. */
    let status = $state<LocalPlane | null>(null);
    let failed = $state("");
    let saved = $state("");
    let url = $state("");
    let llm = $state("");
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
                llm = status.stored.local_model;
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
            local_model: llm,
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

<section class="k-card" style="margin-bottom:24px">
    <div class="k-spread" style="margin-bottom:16px">
        <div class="k-eyebrow">Local machine</div>
        {#if busy}
            <span class="scan run" aria-hidden="true"
                ><i class="on"></i><i class="on"></i><i class="on head"></i><i></i><i></i></span
            >
        {:else if failed}
            <Tag state="block">Unreachable</Tag>
        {:else if status?.ready}
            <Tag state="live">Live</Tag>
        {:else if status}
            <Tag state="queue">Not ready</Tag>
        {/if}
    </div>

    {#if failed}
        <p class="k-note" role="status">Could not read the local plane: {failed}</p>
    {:else if !status}
        <p class="k-note">Checking…</p>
    {:else}
        <p class="k-note" style="margin-bottom:16px">{status.line}</p>

        <div class="k-row" style="align-items:flex-end;margin-bottom:16px">
            <label class="grow">
                <span class="k-eyebrow" style="display:block;margin-bottom:8px">Server address</span>
                <span class="k-input"
                    ><input
                        type="url"
                        bind:value={url}
                        placeholder="Found automatically"
                        autocomplete="off"
                /></span>
            </label>
            <label class="grow">
                <span class="k-eyebrow" style="display:block;margin-bottom:8px">LLM</span>
                <select bind:value={llm}>
                    <option value="">First one the server lists</option>
                    {#each status.models as one (one)}
                        <option value={one}>{one}</option>
                    {/each}
                </select>
            </label>
            <label class="grow">
                <span class="k-eyebrow" style="display:block;margin-bottom:8px"
                    >Search service address</span
                >
                <span class="k-input"
                    ><input
                        type="url"
                        bind:value={searchUrl}
                        placeholder="http://127.0.0.1:7000"
                        autocomplete="off"
                /></span>
            </label>
            <label class="grow">
                <span class="k-eyebrow" style="display:block;margin-bottom:8px"
                    >Wait for one answer, in seconds</span
                >
                <input type="number" min="10" bind:value={timeout} placeholder="300" />
            </label>
        </div>

        <div class="k-row">
            <Key type="submit" onclick={save} disabled={busy}>Save</Key>
            <Key variant="ghost" onclick={() => load(false)} disabled={busy}>Check again</Key>
            {#if saved}<span class="k-note" role="status">{saved}</span>{/if}
        </div>
    {/if}
</section>

<style>
    .grow {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 220px;
    }
</style>
