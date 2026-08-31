<script lang="ts">
    import { api } from "../lib/api";
    import type { Pack, PackEvent, Revision } from "../lib/types";

    let packs = $state<Pack[]>([]);
    let error = $state("");
    let installMessage = $state("");
    let installState = $state("results");
    let files = $state<FileList | null>(null);
    let lifecycle = $state<
        Record<string, { revisions: Revision[]; events: PackEvent[] }>
    >({});

    async function refresh() {
        try {
            packs = await api.packs();
            error = "";
        } catch (e) {
            error = (e as Error).message;
        }
    }

    async function install() {
        const file = files?.[0];
        if (!file) {
            installState = "error";
            installMessage = "Choose a .kpack file first.";
            return;
        }
        installState = "loading";
        installMessage = `Installing ${file.name}…`;
        try {
            const data = await api.installPack(file);
            installState = "results";
            installMessage = `Installed ${data.pack.name} ${data.pack.version}`;
            await refresh();
        } catch (e) {
            installState = "error";
            installMessage = `Install failed: ${(e as Error).message}`;
        }
    }

    async function toggle(pack: Pack) {
        await api.setEnabled(pack.pack_id, !pack.enabled);
        await refresh();
    }

    async function loadLifecycle(packId: string) {
        const [revisions, events] = await Promise.all([
            api.revisions(packId),
            api.events(packId),
        ]);
        lifecycle = { ...lifecycle, [packId]: { revisions, events } };
    }

    const ready = refresh();
</script>

<h2>Installed packs</h2>

<div class="row">
    <input type="file" accept=".kpack,application/octet-stream" bind:files />
    <button onclick={install}>Install pack</button>
</div>
{#if installMessage}
    <p class="state {installState}" aria-live="polite">{installMessage}</p>
{/if}

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if error}
        <p class="state error">Could not load this view: {error}</p>
    {:else if !packs.length}
        <p class="state empty">No packs installed.</p>
    {:else}
        {#each packs as pack (pack.pack_id)}
            <article class="card">
                <h3>{pack.name} <span class="badge">{pack.version}</span></h3>
                <p class="meta">
                    {pack.pack_id} · {pack.subjects} subjects · {pack.claims} claims · {pack.evidence}
                    evidence · digest {pack.digest}
                </p>
                <div class="row">
                    <button onclick={() => toggle(pack)}>
                        {pack.enabled ? "Disable" : "Enable"}
                    </button>
                    <button class="ghost" onclick={() => loadLifecycle(pack.pack_id)}>
                        Lifecycle
                    </button>
                    {#if !pack.enabled}<span class="meta">disabled</span>{/if}
                </div>
                {#if lifecycle[pack.pack_id]}
                    {@const life = lifecycle[pack.pack_id]}
                    <details open>
                        <summary>Revision history ({life.revisions.length})</summary>
                        {#if life.revisions.length}
                            <table>
                                <thead>
                                    <tr
                                        ><th>Revision</th><th>Installed</th><th>State</th><th
                                        ></th></tr
                                    >
                                </thead>
                                <tbody>
                                    {#each life.revisions as revision}
                                        <tr>
                                            <td>
                                                {revision.version}
                                                <span class="meta"
                                                    >{revision.content_digest.slice(0, 12)}</span
                                                >
                                            </td>
                                            <td class="meta">{revision.installed_at}</td>
                                            <td>{revision.active ? "active" : "retained"}</td>
                                            <td>
                                                {#if !revision.active}
                                                    <button
                                                        onclick={async () => {
                                                            await api.activate(
                                                                pack.pack_id,
                                                                revision.revision_id,
                                                            );
                                                            await refresh();
                                                            await loadLifecycle(pack.pack_id);
                                                        }}>Activate</button
                                                    >
                                                {/if}
                                            </td>
                                        </tr>
                                    {/each}
                                </tbody>
                            </table>
                        {:else}
                            <p class="state empty">No retained revisions.</p>
                        {/if}
                        <p class="meta">{life.events.length} lifecycle event(s)</p>
                        {#each life.events.slice(-5).reverse() as event}
                            <div class="event">
                                <strong>{event.action}</strong> · {event.created_at}
                                <span class="meta">{event.revision_id}</span>
                            </div>
                        {/each}
                    </details>
                {/if}
            </article>
        {/each}
    {/if}
{/await}
