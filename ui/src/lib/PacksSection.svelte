<script lang="ts">
    import FilePick from "./FilePick.svelte";
    import Icon from "./Icon.svelte";
    import { count } from "./plural";
    import { remedyFor } from "./failure";
    import { api, ApiError } from "./api";
    import EmptyState from "./EmptyState.svelte";
    import Failure from "./Failure.svelte";
    import type { Pack, PackEvent, Revision } from "./types";

    /* The installed catalogs, at the top of Browse (B167).
     *
     * This was the Packs screen. It is a section of Browse now because what is
     * installed is the first thing to know before asking what is known, and a
     * rail row for it only told the reader that the two were apart. `onchange`
     * is how Browse learns an install, a switch-off or an uninstall happened:
     * its own lists are read from the same store and would otherwise go stale
     * under it.
     *
     * The Updates block that stood here is gone (B166). Installed packs follow
     * the index on their own, weekly, in the background (`app/packautoupdate.py`);
     * `GET /api/packs/updates` stays for Overview and the first-run screen.
     */
    let { onchange = () => {} }: { onchange?: () => void } = $props();

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

    async function refresh(notify = true) {
        try {
            packs = await api.packs();
            failure = null;
        } catch (e) {
            failure = e;
        }
        if (notify) onchange();
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

    // Not announced: Browse read the same store a moment ago.
    const ready = refresh(false);
</script>

<h3><Icon name="packs" size={20} /> Catalogs</h3>

<div class="row">
    <FilePick
        label="Choose a .kpack file"
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
{#if installMessage}
    <p class="state {installState}" aria-live="polite">{installMessage}</p>
{/if}

{#await ready}
    <p class="state loading">Loading catalogs…</p>
{:then}
    {#if failure}
        <Failure error={failure} retry={() => refresh()} />
    {:else if !packs.length}
        <!-- Screen-level absence, so it gets the screen-level idiom: a title,
             why it is empty, and the one thing to do about it. The one-line
             "No packs installed." this replaced was the same fact with the
             next step left as an exercise. -->
        <EmptyState
            title="No catalogs installed"
            detail="A catalog is the knowledge. With none installed, a lookup succeeds
                    and finds nothing. Choose a .kpack file above to install one."
        />
    {:else}
        {#each packs as pack (pack.pack_id)}
            <article class="card">
                <h4>{pack.name} <span class="badge">{pack.version}</span></h4>
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
