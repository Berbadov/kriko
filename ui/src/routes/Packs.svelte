<script lang="ts">
    import { count } from "../lib/plural";
    import { remedyFor } from "../lib/failure";
    import { api, ApiError } from "../lib/api";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { follow, stateWord } from "../lib/jobs";
    import type { Job, Pack, PackEvent, PackUpdates, Revision } from "../lib/types";

    let packs = $state<Pack[]>([]);
    // The exception, not its message — see Failure: the remedy comes off
    // the status, which a string has already discarded.
    let failure = $state<unknown>(null);
    let installMessage = $state("");
    let installFailure = $state<unknown>(null);
    let installState = $state("results");
    let files = $state<FileList | null>(null);
    // Set only while a downgrade is pending confirmation — the offered file
    // is older than what is installed, and the server has already refused it
    // once (knowledge-13). Installing anyway resends the same file with
    // `allow_downgrade`.
    let downgradeOffer = $state<{ file: File; installed: string; offered: string } | null>(
        null,
    );
    let lifecycle = $state<
        Record<string, { revisions: Revision[]; events: PackEvent[] }>
    >({});
    // Which pack an action is in flight for, so a second click while the
    // first request is still in the air does nothing (knowledge-12).
    let busy = $state<Record<string, boolean>>({});
    // Per-pack failure from Disable/Enable, Activate or Lifecycle, kept apart
    // from the screen-level `failure` — one pack's request failing must not
    // blank out every other pack's card (knowledge-4).
    let actionError = $state<Record<string, unknown>>({});
    let confirmUninstall = $state("");

    async function refresh() {
        try {
            packs = await api.packs();
            failure = null;
        } catch (e) {
            failure = e;
        }
    }

    async function install(allowDowngrade = false) {
        const file = downgradeOffer?.file ?? files?.[0];
        if (!file) {
            installState = "error";
            installMessage = "Choose a .kpack file first.";
            return;
        }
        installState = "loading";
        installFailure = null;
        installMessage = `Installing ${file.name}…`;
        try {
            const data = await api.installPack(file, allowDowngrade);
            installState = "results";
            installMessage = `Installed ${data.pack.name} ${data.pack.version}`;
            downgradeOffer = null;
            await refresh();
        } catch (e) {
            if (
                e instanceof ApiError
                && e.status === 409
                && e.detail
                && typeof e.detail === "object"
                && (e.detail as { kind?: string }).kind === "downgrade_refused"
            ) {
                const detail = e.detail as { installed?: string; offered?: string };
                downgradeOffer = {
                    file,
                    installed: detail.installed ?? "the installed version",
                    offered: detail.offered ?? "this file",
                };
                installState = "error";
                installMessage = "";
                return;
            }
            installState = "error";
            installMessage = remedyFor(e).headline;
            installFailure = e;
        }
    }

    async function toggle(pack: Pack) {
        if (busy[pack.pack_id]) return;
        busy = { ...busy, [pack.pack_id]: true };
        actionError = { ...actionError, [pack.pack_id]: null };
        try {
            await api.setEnabled(pack.pack_id, !pack.enabled);
            await refresh();
        } catch (e) {
            actionError = { ...actionError, [pack.pack_id]: e };
        } finally {
            busy = { ...busy, [pack.pack_id]: false };
        }
    }

    async function loadLifecycle(packId: string) {
        if (lifecycle[packId]) {
            // Pressed again: close it rather than refetching what is already
            // on screen (knowledge-32).
            const { [packId]: _drop, ...rest } = lifecycle;
            lifecycle = rest;
            return;
        }
        if (busy[packId]) return;
        busy = { ...busy, [packId]: true };
        actionError = { ...actionError, [packId]: null };
        try {
            const [revisions, events] = await Promise.all([
                api.revisions(packId),
                api.events(packId),
            ]);
            lifecycle = { ...lifecycle, [packId]: { revisions, events } };
        } catch (e) {
            actionError = { ...actionError, [packId]: e };
        } finally {
            busy = { ...busy, [packId]: false };
        }
    }

    async function activateRevision(pack: Pack, revisionId: string) {
        const key = `${pack.pack_id}:${revisionId}`;
        if (busy[key]) return;
        busy = { ...busy, [key]: true };
        actionError = { ...actionError, [pack.pack_id]: null };
        try {
            await api.activate(pack.pack_id, revisionId);
            await refresh();
            delete lifecycle[pack.pack_id];
            await loadLifecycle(pack.pack_id);
        } catch (e) {
            actionError = { ...actionError, [pack.pack_id]: e };
        } finally {
            busy = { ...busy, [key]: false };
        }
    }

    async function uninstall(pack: Pack) {
        if (confirmUninstall !== pack.pack_id) {
            // First click asks; it does not act — an uninstall drops the
            // pack's rows and cannot be undone from here (knowledge-23).
            confirmUninstall = pack.pack_id;
            return;
        }
        confirmUninstall = "";
        if (busy[pack.pack_id]) return;
        busy = { ...busy, [pack.pack_id]: true };
        actionError = { ...actionError, [pack.pack_id]: null };
        try {
            await api.uninstallPack(pack.pack_id);
            await refresh();
        } catch (e) {
            actionError = { ...actionError, [pack.pack_id]: e };
        } finally {
            busy = { ...busy, [pack.pack_id]: false };
        }
    }

    const dateFmt = new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    });
    function formatWhen(iso: string): string {
        const d = new Date(iso);
        return Number.isNaN(d.getTime()) ? iso : dateFmt.format(d);
    }
    // Full value stays in `title` for anyone who needs to paste it whole;
    // the row shows enough to tell two revisions apart, not sixty-four hex
    // characters (knowledge-32).
    const short = (id: string) => (id.length > 10 ? `${id.slice(0, 10)}…` : id);

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
            updates = await api.packUpdates();
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
    <input
        type="file"
        accept=".kpack,application/octet-stream"
        bind:files
        onchange={() => {
            downgradeOffer = null;
            installFailure = null;
        }}
    />
    <button class="primary" disabled={!files?.length || installState === "loading"} onclick={() => install()}>
        Install pack
    </button>
</div>
{#if installFailure}
    <Failure error={installFailure} retry={() => install()} />
{/if}
{#if downgradeOffer}
    <p class="state error">
        {downgradeOffer.installed} is installed; {downgradeOffer.offered} is older.
        <button onclick={() => install(true)}>Install anyway</button>
        <button class="ghost" onclick={() => (downgradeOffer = null)}>Cancel</button>
    </p>
{/if}
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
        <p class="state error">Could not reach the pack index: {updates.error}</p>
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
                    evidence · digest <span title={pack.digest}>{short(pack.digest)}</span>
                </p>
                <div class="row">
                    <button
                        aria-label="{pack.enabled ? 'Disable' : 'Enable'} {pack.name}"
                        disabled={busy[pack.pack_id]}
                        onclick={() => toggle(pack)}
                    >
                        {pack.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                        class="ghost"
                        aria-label="Lifecycle for {pack.name}"
                        disabled={busy[pack.pack_id]}
                        onclick={() => loadLifecycle(pack.pack_id)}
                    >
                        {lifecycle[pack.pack_id] ? "Hide lifecycle" : "Lifecycle"}
                    </button>
                    <button
                        class="ghost"
                        aria-label="Uninstall {pack.name}"
                        disabled={busy[pack.pack_id]}
                        onclick={() => uninstall(pack)}
                    >
                        {confirmUninstall === pack.pack_id ? "Really uninstall?" : "Uninstall"}
                    </button>
                    {#if confirmUninstall === pack.pack_id}
                        <button class="ghost" onclick={() => (confirmUninstall = "")}>
                            Cancel
                        </button>
                    {/if}
                    {#if !pack.enabled}<span class="meta">disabled</span>{/if}
                </div>
                {#if actionError[pack.pack_id]}
                    <Failure
                        error={actionError[pack.pack_id]}
                        retry={() => (actionError = { ...actionError, [pack.pack_id]: null })}
                    />
                {/if}
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
                                                <span class="meta" title={revision.content_digest}
                                                    >{short(revision.content_digest)}</span
                                                >
                                            </td>
                                            <td class="meta">{formatWhen(revision.installed_at)}</td>
                                            <td>{revision.active ? "active" : "retained"}</td>
                                            <td>
                                                {#if !revision.active}
                                                    <button
                                                        disabled={busy[
                                                            `${pack.pack_id}:${revision.revision_id}`
                                                        ]}
                                                        onclick={() =>
                                                            activateRevision(pack, revision.revision_id)}
                                                        >Activate</button
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
                                <strong>{event.action}</strong> · {formatWhen(event.created_at)}
                                <span class="meta" title={event.revision_id}
                                    >{short(event.revision_id)}</span
                                >
                            </div>
                        {/each}
                    </details>
                {/if}
            </article>
        {/each}
    {/if}
{/await}
