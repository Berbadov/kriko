<script lang="ts">
    import { count } from "../lib/plural";
    import { remedyFor } from "../lib/failure";
    import { api } from "../lib/api";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { follow, stateWord } from "../lib/jobs";
    import type { Job, Pack, PackEvent, PackUpdates, Revision } from "../lib/types";

    let packs = $state<Pack[]>([]);
    // The exception, not its message — see Failure: the remedy comes off
    // the status, which a string has already discarded.
    let failure = $state<unknown>(null);
    let installMessage = $state("");
    let installState = $state("results");
    let files = $state<FileList | null>(null);
    let lifecycle = $state<
        Record<string, { revisions: Revision[]; events: PackEvent[] }>
    >({});

    async function refresh() {
        try {
            packs = await api.packs();
            failure = null;
        } catch (e) {
            failure = e;
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
            installMessage = remedyFor(e).headline;
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

    // Updating is two operations, deliberately: checking is a cheap request
    // whose answer is a table, installing is a job whose progress outlives the
    // page. Collapsing them into one button would mean either a blocking
    // download or a check nobody can read.
    let updates = $state<PackUpdates | null>(null);
    let checking = $state(false);
    let updateJob = $state<Job | null>(null);

    const WORDS: Record<string, string> = {
        available: "update available",
        up_to_date: "up to date",
        not_installed: "not installed",
        refused: "refused",
        unknown: "unknown",
    };

    async function check() {
        checking = true;
        try {
            updates = await api.packUpdates(true);
        } catch (e) {
            updates = { index_url: "", error: remedyFor(e).headline, packs: [] };
        } finally {
            checking = false;
        }
    }

    async function applyUpdate(packId?: string) {
        updateJob = null;
        try {
            const { job_id } = await api.updatePacks(packId);
            updateJob = await api.job(job_id);
            follow(job_id, async (job) => {
                updateJob = job;
                if (job.done) {
                    await refresh();
                    await check();
                }
            });
        } catch (e) {
            updateJob = { state: "failed", message: remedyFor(e).headline, done: true } as Job;
        }
    }

    const actionable = (u: PackUpdates | null) =>
        (u?.packs ?? []).filter((p) => p.state === "available" || p.state === "not_installed");

    const ready = refresh();
</script>

<h2>Installed packs</h2>

<div class="row">
    <input type="file" accept=".kpack,application/octet-stream" bind:files />
    <button class="primary" onclick={install}>Install pack</button>
</div>
<section class="card">
    <h3>Updates</h3>
    <div class="row">
        <button onclick={check} disabled={checking}>
            {checking ? "Checking…" : "Check for updates"}
        </button>
        {#if actionable(updates).length}
            <button onclick={() => applyUpdate()}>
                Update all ({actionable(updates).length})
            </button>
        {/if}
        {#if updates?.index_url}<span class="meta">{updates.index_url}</span>{/if}
    </div>
    {#if updates?.error}
        <p class="state error">{updates.error}</p>
        {#if updates.error_detail}
            <details>
                <summary class="meta">Show the details</summary>
                <p class="meta">{updates.error_detail}</p>
            </details>
        {/if}
    {/if}
    {#if updates && !updates.error}
        {#if !updates.packs.length}
            <p class="state empty">
                The index answered, and lists no packs at all — so there is nothing
                to update to yet. Nothing installed has gone stale.
            </p>
        {:else}
            <table>
                <thead>
                    <tr><th>Pack</th><th>Installed</th><th>Offered</th><th>State</th><th></th></tr>
                </thead>
                <tbody>
                    {#each updates.packs as row (row.pack_id)}
                        <tr>
                            <td>{row.name}</td>
                            <td class="meta">{row.installed_version || "—"}</td>
                            <td class="meta">{row.offered_version || "—"}</td>
                            <td>
                                {WORDS[row.state] ?? row.state}
                                <span class="meta">{row.reason}</span>
                            </td>
                            <td>
                                {#if row.state === "available" || row.state === "not_installed"}
                                    <button onclick={() => applyUpdate(row.pack_id)}>
                                        {row.state === "available" ? "Update" : "Install"}
                                    </button>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {/if}
    {/if}
    {#if updateJob}
        <p class="state {updateJob.state === 'failed' ? 'error' : 'results'}" aria-live="polite">
            <span class="badge state-{updateJob.state}">{stateWord(updateJob)}</span>
            {updateJob.message}
        </p>
    {/if}
</section>

{#if installMessage}
    <p class="state {installState}" aria-live="polite">{installMessage}</p>
{/if}

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if failure}
        <Failure error={failure} retry={refresh} />
    {:else if !packs.length}
        <!-- Screen-level absence, so it gets the screen-level idiom: a title,
             why it is empty, and the one thing to do about it. The one-line
             "No packs installed." this replaced was the same fact with the
             next step left as an exercise. -->
        <EmptyState
            title="No packs installed"
            detail="A pack is the knowledge — with none installed, a lookup succeeds
                    and finds nothing. The file picker above installs a .kpack, and
                    Check for updates fetches the index."
        />
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
                        <p class="meta">{count(life.events.length, "lifecycle event")}</p>
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
