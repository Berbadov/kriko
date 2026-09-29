<script lang="ts">
    import Async from "../lib/Async.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api, ApiError } from "../lib/api";
    import { follow } from "../lib/jobs";
    import { JobFailedError, PackInstallFailedError } from "../lib/failure";

    let { onDone }: { onDone: () => void } = $props();

    let busy = $state(false);
    let log = $state("");
    // The exception itself, not its message. This is the reader's first
    // minute with Kriko: a sentence about what to do next is worth more here
    // than anywhere else in the app, and a string has already thrown away the
    // status Failure needs to write one (B72).
    let failure = $state<unknown>(null);

    // A first run is a deliberate ask, not a background hint — this is the
    // one screen where a slow or unreachable index earns paying for a real
    // network round trip rather than taking a cached "not checked yet".
    const offer = api.packUpdates(true);

    // Installing is a job, because a download outlives the request — the same
    // path Packs uses, so a pack installed here has the same provenance as one
    // installed later.
    async function install() {
        busy = true;
        failure = null;
        try {
            const { job_id } = await api.updatePacks();
            // follow() returns the way to stop watching, not a promise — the
            // job's own `done` is what says the pack is on disk. Awaiting the
            // returned function would resolve at once and hand the reader an
            // app that still knows nothing.
            await new Promise<void>((resolve) => {
                follow(job_id, (job) => {
                    log = job.message || job.log.split("\n").slice(-1)[0] || "";
                    if (!job.done) return;
                    if (job.state === "failed")
                        failure = new JobFailedError(job.message || "The pack could not be downloaded.");
                    resolve();
                });
            });
            if (!failure) onDone();
        } catch (e) {
            failure = e;
        } finally {
            busy = false;
        }
    }

    async function chooseFile(event: Event) {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        // The browser only fires `change` when the input's value differs
        // from what it already held, so choosing the same file a second
        // time — the obvious thing to do after "that file didn't work,
        // pick another" turns out to have been the same file by mistake —
        // fired nothing at all (B145 settings-17). Clearing it here means
        // the next pick, same file or not, is always a fresh value.
        input.value = "";
        busy = true;
        failure = null;
        try {
            await api.installPack(file);
            onDone();
        } catch (e) {
            failure = e instanceof ApiError ? new PackInstallFailedError(e) : e;
        } finally {
            busy = false;
        }
    }
</script>

<section class="welcome">
    <h2>Kriko is installed. It knows nothing yet.</h2>
    <p class="hero-sub">
        The engine ships empty on purpose: knowledge changes weekly and the app rarely,
        so they update on separate clocks. Install a knowledge pack and the app has
        something to answer with. Everything stays on this machine.
    </p>

    <Async promise={offer} loading="Looking for packs…">
        {#snippet children(updates)}
            {#if updates.error}
                <p class="state no-match">
                    {updates.error} You can install a pack from a file instead, or skip
                    and do it later from Packs.
                </p>
                {#if updates.error_detail}
                    <details>
                        <summary class="meta">Show the details</summary>
                        <p class="meta">{updates.error_detail}</p>
                    </details>
                {/if}
            {:else if !updates.packs.length}
                <p class="state empty">
                    The index offers no packs right now. Skip for now; Packs will check
                    again whenever you ask it to.
                </p>
            {:else}
                <ul class="worklist">
                    {#each updates.packs as pack (pack.pack_id)}
                        <li>
                            <strong>{pack.name}</strong>
                            <span class="meta"
                                >version {pack.offered_version ?? "unknown"}</span
                            >
                        </li>
                    {/each}
                </ul>
                <p class="meta">from {updates.index_url}</p>
                <div class="row">
                    <button class="primary" onclick={install} disabled={busy}>
                        {busy ? "Installing…" : "Install and get started"}
                    </button>
                </div>
            {/if}

            <div class="field wide">
                <label for="kpack">Or install a .kpack file you already have</label>
                <input id="kpack" type="file" accept=".kpack" onchange={chooseFile} />
            </div>

            <div class="row">
                <button class="ghost" onclick={onDone}>Skip for now</button>
            </div>

            <div aria-live="polite">
                {#if log}<p class="meta">{log}</p>{/if}
                {#if failure}<Failure error={failure} retry={install} />{/if}
            </div>
        {/snippet}
    </Async>
</section>
